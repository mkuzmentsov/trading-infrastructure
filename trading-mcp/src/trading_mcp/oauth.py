"""Self-contained OAuth 2.1 authorization server for the MCP endpoint.

The MCP authorization spec (2025-06-18, RFC 9728 + RFC 8414 + PKCE) lets a
server be its own authorization server so browser/mobile clients (claude.ai,
Claude mobile) — which cannot send a custom ``Authorization`` header — can
obtain a token through the standard OAuth code+PKCE flow instead.

Design (single-user personal server, no external IdP, no database):
  * All tokens are STATELESS signed JWTs (HS256 over ``MCP_OAUTH_SECRET``) — they
    survive pod restarts with zero storage. Auth codes (5 min), access tokens
    (90 d) and refresh tokens (365 d) are all self-contained.
  * Dynamic client registration returns a random ``client_id`` and does not
    persist it — PKCE (S256) binds the code to the client, which is sufficient
    for one user; there is no client_secret (public client).
  * The one human gate is the ``/authorize`` approval page, protected by
    ``MCP_LOGIN_PASSWORD`` (distinct from the machine ``MCP_AUTH_TOKEN``).

Endpoints (all served WITHOUT the bearer gate, via the outer middleware):
  GET  /.well-known/oauth-protected-resource[...]   RFC 9728 metadata
  GET  /.well-known/oauth-authorization-server[...]  RFC 8414 metadata
  GET  /.well-known/openid-configuration             (alias, some clients probe)
  POST /register                                     dynamic client registration
  GET  /authorize                                    render approval page
  POST /authorize                                    check password -> issue code
  POST /token                                        code|refresh -> tokens

The existing static ``MCP_AUTH_TOKEN`` keeps working unchanged (Claude Code).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send
else:
    Receive = Scope = Send = object

log = logging.getLogger("trading-mcp.oauth")

ACCESS_TTL = 90 * 86400
REFRESH_TTL = 365 * 86400
CODE_TTL = 300


# ── JWT (HS256, stdlib) ─────────────────────────────────────────────────────

def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwt_sign(payload: dict, secret: str) -> str:
    head = _b64u(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{head}.{body}.{_b64u(sig)}"


def jwt_verify(token: str, secret: str) -> dict | None:
    try:
        head, body, sig = token.split(".")
        signing_input = f"{head}.{body}".encode()
        expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64u_dec(sig), expected):
            return None
        payload = json.loads(_b64u_dec(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def validate_access_token(token: str, secret: str, issuer: str) -> bool:
    p = jwt_verify(token, secret)
    return bool(p and p.get("typ") == "access" and p.get("iss") == issuer)


# ── OAuth ASGI middleware ────────────────────────────────────────────────────

class OAuthMiddleware:
    """Handles the OAuth + discovery routes; passes everything else through to
    the inner app (bearer middleware -> MCP). Runs OUTERMOST so these paths are
    reachable without a token."""

    def __init__(self, app, secret: str, issuer: str, login_password: str) -> None:
        self.app = app
        self.secret = secret
        self.issuer = issuer.rstrip("/")
        self.resource = f"{self.issuer}/mcp"
        self.login = login_password

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path.startswith("/.well-known/oauth-protected-resource"):
            return await self._json(send, {
                "resource": self.resource,
                "authorization_servers": [self.issuer],
                "bearer_methods_supported": ["header"],
            })
        if (path.startswith("/.well-known/oauth-authorization-server")
                or path.startswith("/.well-known/openid-configuration")):
            return await self._json(send, self._as_metadata())
        if path == "/register" and method == "POST":
            return await self._register(receive, send)
        if path == "/authorize":
            if method == "GET":
                return await self._authorize_get(scope, send)
            if method == "POST":
                return await self._authorize_post(receive, send)
        if path == "/token" and method == "POST":
            return await self._token(receive, send)

        await self.app(scope, receive, send)

    def _as_metadata(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "registration_endpoint": f"{self.issuer}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["mcp"],
        }

    # ----- dynamic client registration -----------------------------------
    async def _register(self, receive: Receive, send: Send) -> None:
        body = await _read_body(receive)
        try:
            req = json.loads(body or b"{}")
        except Exception:
            req = {}
        client_id = "mcp-" + secrets.token_urlsafe(16)
        resp = {
            "client_id": client_id,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": req.get("redirect_uris", []),
            "client_id_issued_at": int(time.time()),
        }
        await self._json(send, resp, status=201)

    # ----- authorize (approval page) -------------------------------------
    async def _authorize_get(self, scope: Scope, send: Send) -> None:
        q = dict(urllib.parse.parse_qsl(scope.get("query_string", b"").decode()))
        if q.get("code_challenge_method") not in ("S256", None):
            return await self._json(send, {"error": "invalid_request",
                                           "error_description": "S256 required"}, 400)
        html = self._form_html(q, error="")
        await self._html(send, html)

    async def _authorize_post(self, receive: Receive, send: Send) -> None:
        body = await _read_body(receive)
        f = dict(urllib.parse.parse_qsl(body.decode()))
        if not hmac.compare_digest(f.get("password", ""), self.login):
            return await self._html(send, self._form_html(f, error="Wrong password"), status=401)
        code = jwt_sign({
            "typ": "code",
            "iss": self.issuer,
            "cc": f.get("code_challenge", ""),
            "redirect_uri": f.get("redirect_uri", ""),
            "scope": f.get("scope", "mcp"),
            "iat": int(time.time()),
            "exp": int(time.time()) + CODE_TTL,
        }, self.secret)
        redirect = f.get("redirect_uri", "")
        sep = "&" if "?" in redirect else "?"
        loc = f"{redirect}{sep}code={urllib.parse.quote(code)}"
        if f.get("state"):
            loc += f"&state={urllib.parse.quote(f['state'])}"
        await self._redirect(send, loc)

    # ----- token ---------------------------------------------------------
    async def _token(self, receive: Receive, send: Send) -> None:
        body = await _read_body(receive)
        f = dict(urllib.parse.parse_qsl(body.decode()))
        grant = f.get("grant_type")
        if grant == "authorization_code":
            code = jwt_verify(f.get("code", ""), self.secret)
            if not code or code.get("typ") != "code":
                return await self._json(send, {"error": "invalid_grant"}, 400)
            verifier = f.get("code_verifier", "")
            challenge = _b64u(hashlib.sha256(verifier.encode()).digest())
            if not hmac.compare_digest(challenge, code.get("cc", "")):
                return await self._json(send, {"error": "invalid_grant",
                                               "error_description": "PKCE failed"}, 400)
            if f.get("redirect_uri", "") != code.get("redirect_uri", ""):
                return await self._json(send, {"error": "invalid_grant",
                                               "error_description": "redirect_uri mismatch"}, 400)
            return await self._issue(send, code.get("scope", "mcp"))
        if grant == "refresh_token":
            rt = jwt_verify(f.get("refresh_token", ""), self.secret)
            if not rt or rt.get("typ") != "refresh":
                return await self._json(send, {"error": "invalid_grant"}, 400)
            return await self._issue(send, rt.get("scope", "mcp"))
        return await self._json(send, {"error": "unsupported_grant_type"}, 400)

    async def _issue(self, send: Send, scope: str) -> None:
        now = int(time.time())
        access = jwt_sign({"typ": "access", "iss": self.issuer, "sub": "owner",
                           "aud": self.resource, "scope": scope,
                           "iat": now, "exp": now + ACCESS_TTL}, self.secret)
        refresh = jwt_sign({"typ": "refresh", "iss": self.issuer, "sub": "owner",
                            "scope": scope, "iat": now, "exp": now + REFRESH_TTL},
                           self.secret)
        await self._json(send, {
            "access_token": access, "token_type": "Bearer",
            "expires_in": ACCESS_TTL, "refresh_token": refresh, "scope": scope,
        })

    # ----- rendering helpers ---------------------------------------------
    def _form_html(self, params: dict, error: str) -> str:
        keep = ("client_id", "redirect_uri", "state", "code_challenge",
                "code_challenge_method", "scope", "response_type", "resource")
        hidden = "".join(
            f'<input type="hidden" name="{k}" value="{_esc(params.get(k, ""))}">'
            for k in keep if params.get(k))
        err = f'<p style="color:#c00">{_esc(error)}</p>' if error else ""
        return f"""<!doctype html><html><head><meta name="viewport"
content="width=device-width,initial-scale=1"><title>trading-mcp login</title>
<style>body{{font-family:system-ui;max-width:340px;margin:12vh auto;padding:0 20px}}
input{{width:100%;padding:12px;margin:8px 0;font-size:16px;box-sizing:border-box}}
button{{width:100%;padding:12px;font-size:16px;background:#111;color:#fff;border:0;border-radius:8px}}
</style></head><body><h2>trading-mcp</h2>
<p>Authorize this device to access your trading server.</p>{err}
<form method="post" action="/authorize">{hidden}
<input type="password" name="password" placeholder="Login password" autofocus autocomplete="current-password">
<button type="submit">Approve</button></form></body></html>"""

    async def _json(self, send: Send, obj: dict, status: int = 200) -> None:
        await _respond(send, status, json.dumps(obj).encode(),
                       b"application/json", [(b"cache-control", b"no-store")])

    async def _html(self, send: Send, html: str, status: int = 200) -> None:
        await _respond(send, status, html.encode(), b"text/html; charset=utf-8")

    async def _redirect(self, send: Send, location: str) -> None:
        await _respond(send, 302, b"", b"text/plain",
                       [(b"location", location.encode())])


# ── ASGI byte helpers ────────────────────────────────────────────────────────

async def _read_body(receive: Receive) -> bytes:
    chunks = b""
    while True:
        event = await receive()
        if event["type"] == "http.request":
            chunks += event.get("body", b"")
            if not event.get("more_body"):
                break
        else:
            break
    return chunks


async def _respond(send: Send, status: int, body: bytes,
                   content_type: bytes = b"application/json",
                   extra: list | None = None) -> None:
    headers = [(b"content-type", content_type),
               (b"content-length", str(len(body)).encode())]
    if extra:
        headers.extend(extra)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
