"""Wake-up bus: feeds signal "new data arrived", consumers wake instantly.

Replaces fixed-interval polling: the eval loop awaits `wait()` and runs the
moment a Binance trade or a CLOB book update lands, instead of up to one full
poll interval later. Falls back to `timeout` so a quiet feed still gets
periodic evaluation (settlement checks, t_left-driven gates).
"""
from __future__ import annotations

import asyncio
import time


class TickBus:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.last_source: str = ""
        self.last_signal_ts: float = 0.0    # exchange/server event time (s)
        self.last_arrival_ts: float = 0.0   # local arrival time (s)
        self.signals: int = 0

    def fire(self, source: str, signal_ts: float = 0.0) -> None:
        """Called from feed callbacks (same event loop). Cheap by design."""
        self.last_source = source
        self.last_signal_ts = signal_ts
        self.last_arrival_ts = time.time()
        self.signals += 1
        self._event.set()

    async def wait(self, timeout: float) -> bool:
        """True → woken by a feed event; False → timeout tick."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            self._event.clear()
            return True
        except asyncio.TimeoutError:
            return False


tick_bus = TickBus()
