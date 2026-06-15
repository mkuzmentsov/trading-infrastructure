"""Live runner (§9 Phase 6–7) — wires the shared engine to a live venue adapter.

Identical engine to the backtest (NFR1). Differences: WallClock, LiveSource from
the active venue, and a real ExecutionAdapter. Adds the operational shell — safe
restart from persisted state (NFR4), heartbeat/deadman, and the paper-trading mode
that must clear before real capital (§4 paper gate).
"""

from __future__ import annotations

from ..config import BotConfig
from .loop import TradingEngine


class LiveRunner:
    def __init__(self, config: BotConfig, paper: bool = True) -> None:
        self.config = config
        self.paper = paper  # paper-trading gate before real capital (§4)

    def build_engine(self) -> TradingEngine:
        """Same TradingEngine as backtest, with WallClock + LiveSource + venue adapter
        (or a paper adapter when ``paper`` is True)."""
        raise NotImplementedError("assemble live engine; on_restart() to reconcile state (NFR4)")

    def run(self) -> None:
        raise NotImplementedError("oms.on_restart(); then engine.run(live_event_stream) forever")
