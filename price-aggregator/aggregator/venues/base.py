"""Venue feed interface. A feed connects to one exchange, subscribes to the
configured symbols, and pushes updates into the shared SymbolState via the
provided registry callback. Feeds own their reconnect loop and never raise out."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from ..state import SymbolState

log = logging.getLogger("agg.venue")


class VenueFeed:
    name: str = "base"

    def __init__(self, symbols: list[str], get_state: Callable[[str], SymbolState],
                 depth_levels: int = 10) -> None:
        self.symbols = symbols
        self._get_state = get_state
        self.depth_levels = depth_levels

    def state(self, symbol: str) -> SymbolState:
        return self._get_state(symbol)

    async def run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def run_forever(self) -> None:
        backoff = 1
        while True:
            try:
                await self.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("%s feed reconnect in %ds: %s", self.name, backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            else:
                backoff = 1
