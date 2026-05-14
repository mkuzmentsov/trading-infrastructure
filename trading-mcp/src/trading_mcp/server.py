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

from .exchanges import aggregator, binance, hyperliquid, kraken, whitebit

log = logging.getLogger("trading-mcp")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

mcp = FastMCP("trading-mcp")


def _register_all() -> None:
    summary: list[str] = []
    for module in (binance, kraken, hyperliquid, whitebit, aggregator):
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
    log.info("Starting trading-mcp on %s:%s (streamable-http)", host, port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
