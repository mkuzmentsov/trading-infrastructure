"""Backtest harness (§3) — wires the shared engine to historical data + a fill
simulator. NOT a separate strategy code path: only the source and adapter differ.

A run is pinned to (data snapshot id + git commit + config) for provenance; no
provenance -> not trusted (§3.4, NFR2). Output: equity curve, returns series,
trade-by-trade ledger, and the full metrics suite (§3.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import BotConfig
from .loop import TradingEngine


@dataclass
class RunProvenance:
    """Stamped onto every backtest result (§3.4, NFR2)."""

    data_snapshot_id: str
    git_commit: str
    config_hash: str
    started_at: datetime


class Backtester:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def build_engine(self) -> TradingEngine:
        """Assemble the same TradingEngine used live, but with a HistoricalSource and a
        FillSimulator execution adapter (friction.py)."""
        raise NotImplementedError(
            "construct features/strategies/gate/combiner/sizer/risk/oms with SimClock, "
            "HistoricalSource, and FillSimulator; return TradingEngine."
        )

    def run(self, start: datetime, end: datetime):
        """Run the backtest and return (equity_curve, ledger, metrics, provenance)."""
        raise NotImplementedError("drive engine over the historical event stream; collect outputs")
