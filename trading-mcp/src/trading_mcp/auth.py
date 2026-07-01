"""Bearer-token auth for the streamable-HTTP transport.

A single static token (``MCP_AUTH_TOKEN``) gates every MCP request. The server
holds live exchange API keys with trade + withdraw scope, so once it is exposed
beyond loopback this token is the only thing between the public internet and
those keys. Use a long random secret and only ever terminate TLS in front of it.

Implemented as a pure ASGI middleware so it wraps the FastMCP Starlette app
without depending on FastMCP internals. The k8s/LB liveness probe path is left
open so health checks don't need the secret.
"""

from __future__ import annotations

import hmac
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("trading-mcp.auth")

# Served WITHOUT auth so cluster/LB health checks don't need the token.
_OPEN_PATHS = frozenset({"/health", "/healthz"})

_BEARER = b"Bearer "


class BearerAuthMiddleware:
    """Enforce ``Authorization: Bearer <token>`` on every HTTP request except
    the health endpoints. Comparison is constant-time."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in _OPEN_PATHS:
            await self._respond(send, 200, b'{"status":"ok"}')
            return

        if not self._authorized(scope):
            await self._respond(
                send,
                401,
                b'{"error":"unauthorized"}',
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        await self.app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                if not value.startswith(_BEARER):
                    return False
                return hmac.compare_digest(value[len(_BEARER):], self._token)
        return False

    @staticmethod
    async def _respond(
        send: Send,
        status: int,
        body: bytes,
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
