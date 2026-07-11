"""Entry point: wire configured venue feeds into shared state and serve the
broadcast WS. Config via env:
  SYMBOLS       comma list, lowercase (default "btcusdt")
  VENUES        comma list (default "binance")
  WS_HOST       bind host (default "0.0.0.0")
  WS_PORT       bind port (default 8080)
  BROADCAST_MS  tick throttle per symbol (default 100)
  DEPTH_LEVELS  order-book levels to expose (default 10)
  LOG_LEVEL     default INFO
"""
from __future__ import annotations

import asyncio
import logging
import os

from .server import Server
from .state import SymbolState
from .venues import REGISTRY


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip()]


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("agg.main")

    symbols = _env_list("SYMBOLS", "btcusdt")
    venues = _env_list("VENUES", "binance")
    host = os.getenv("WS_HOST", "0.0.0.0")
    port = int(os.getenv("WS_PORT", "8080"))
    broadcast_ms = int(os.getenv("BROADCAST_MS", "100"))
    depth_levels = int(os.getenv("DEPTH_LEVELS", "10"))

    states: dict[str, SymbolState] = {s: SymbolState(s, depth_levels=depth_levels) for s in symbols}
    get_state = lambda s: states[s]  # noqa: E731

    tasks = []
    for v in venues:
        cls = REGISTRY.get(v)
        if cls is None:
            log.warning("unknown venue %r, skipping (known: %s)", v, list(REGISTRY))
            continue
        feed = cls(symbols, get_state, depth_levels=depth_levels)
        tasks.append(asyncio.create_task(feed.run_forever(), name=f"feed_{v}"))
        log.info("started venue feed: %s", v)

    if not tasks:
        raise SystemExit("no valid venues configured")

    server = Server(host, port, symbols,
                    get_snapshot=lambda s: states[s].snapshot(),
                    broadcast_ms=broadcast_ms)
    tasks.append(asyncio.create_task(server.serve(), name="ws_server"))
    log.info("price-aggregator up: symbols=%s venues=%s", symbols, venues)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
