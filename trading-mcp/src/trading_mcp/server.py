"""trading-mcp — multi-exchange MCP server.

Each exchange lives in its own module under ``trading_mcp.exchanges``. A module
exposes a ``register(mcp)`` function that conditionally attaches its tools
(typically skipping when its API credentials are not configured).

Tools are namespaced by exchange prefix, e.g. ``binance_get_portfolio_overview``,
``kraken_get_balances``, so Claude can pick the right one from the name.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

from .exchanges import (
    aggregator,
    binance,
    bitget,
    bybit,
    hyperliquid,
    kraken,
    kraken_futures,
    mexc,
    okx,
    polymarket,
    whitebit,
)

log = logging.getLogger("trading-mcp")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

mcp = FastMCP("trading-mcp")


def _register_all() -> None:
    summary: list[str] = []
    for module in (
        binance, kraken, kraken_futures, hyperliquid, whitebit,
        bybit, mexc, bitget, okx, polymarket, aggregator,
    ):
        short = module.__name__.rsplit(".", 1)[-1]
        try:
            registered = module.register(mcp)
        except Exception:
            log.exception("Failed to register %s tools", module.__name__)
            summary.append(f"  ✗ {short}: register raised")
            continue

        if not registered:
            log.info("Skipped %s (no credentials configured)", module.__name__)
            summary.append(f"  - {short}: skipped (no creds)")
            continue

        log.info("Registered %d tools from %s", registered, module.__name__)

        # Validate live creds for exchange modules. Aggregator has no creds
        # itself — it delegates to other modules — so skip it.
        validator = getattr(module, "validate", None)
        if validator is None:
            summary.append(f"  ✓ {short}: {registered} tools (no validator)")
            continue
        try:
            info = validator()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "Credential validation FAILED for %s: %s", module.__name__, e
            )
            summary.append(f"  ✗ {short}: {registered} tools, VALIDATION FAILED — {e}")
            continue
        log.info("Validated %s: %s", module.__name__, info)
        summary.append(f"  ✓ {short}: {registered} tools, validated {info}")

    log.info("Startup summary:\n%s", "\n".join(summary))


def main() -> None:
    _register_all()

    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8765"))
    mcp.settings.host = host
    mcp.settings.port = port

    # DNS-rebinding protection validates the Host header. Behind an ingress the
    # forwarded Host is the public domain, not localhost, so it must be allowed
    # explicitly. MCP_ALLOWED_HOSTS="host1,host2" allows those (and any :port
    # variant); "*" disables the check (we still have TLS + bearer auth in front).
    allowed_hosts = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
    if allowed_hosts:
        from mcp.server.transport_security import TransportSecuritySettings

        if allowed_hosts == "*":
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
            log.info("DNS-rebinding protection DISABLED (MCP_ALLOWED_HOSTS=*)")
        else:
            hosts = [h.strip() for h in allowed_hosts.split(",") if h.strip()]
            host_patterns = [p for h in hosts for p in (h, f"{h}:*")]
            origins_env = os.environ.get("MCP_ALLOWED_ORIGINS", "").strip()
            if origins_env:
                origins = [o.strip() for o in origins_env.split(",") if o.strip()]
            else:
                origins = [p for h in hosts for p in (f"https://{h}", f"https://{h}:*")]
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=host_patterns,
                allowed_origins=origins,
            )
            log.info("DNS-rebinding protection ON; allowed_hosts=%s", host_patterns)

    app = mcp.streamable_http_app()

    # OAuth 2.1 (browser/mobile clients that can't send a custom header). Enabled
    # when MCP_OAUTH_SECRET + MCP_LOGIN_PASSWORD are set. The static MCP_AUTH_TOKEN
    # keeps working alongside it (Claude Code).
    oauth_secret = os.environ.get("MCP_OAUTH_SECRET", "").strip()
    login_pw = os.environ.get("MCP_LOGIN_PASSWORD", "").strip()
    issuer = os.environ.get("MCP_ISSUER", "").strip().rstrip("/")
    oauth_on = bool(oauth_secret and login_pw and issuer)

    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if token:
        from .auth import BearerAuthMiddleware

        app.add_middleware(
            BearerAuthMiddleware, token=token,
            oauth_secret=oauth_secret if oauth_on else "",
            issuer=issuer if oauth_on else "")
        log.info("Bearer-token auth ENABLED%s",
                 " (+ OAuth access tokens)" if oauth_on else "")
    else:
        log.warning(
            "MCP_AUTH_TOKEN not set — auth DISABLED. Only safe on loopback; "
            "never expose this server publicly without a token."
        )

    if oauth_on:
        # Added AFTER the bearer middleware so it wraps OUTERMOST: OAuth +
        # discovery routes are reachable without a token; everything else falls
        # through to the bearer gate -> MCP app.
        from .oauth import OAuthMiddleware

        app.add_middleware(
            OAuthMiddleware, secret=oauth_secret, issuer=issuer,
            login_password=login_pw)
        log.info("OAuth 2.1 authorization server ENABLED (issuer=%s)", issuer)

    import uvicorn

    log.info("Starting trading-mcp on %s:%s (streamable-http)", host, port)
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
