"""NAV tracking (§2.7).

Marks the book to market each tick, producing the equity series that feeds the
drawdown breaker (risk/drawdown.py), the metrics suite (§3.3), and live-vs-expected
drift (drift.py). One NAV definition for backtest and live (NFR1).
"""

from __future__ import annotations

from ..core.types import Position, Symbol


class NavTracker:
    def __init__(self, starting_cash: float) -> None:
        self.cash = starting_cash
        self.equity: float = starting_cash

    def mark(self, positions: dict[Symbol, Position], prices: dict[Symbol, float]) -> float:
        """Recompute equity = cash + sum(position mark-to-market). Returns NAV."""
        raise NotImplementedError("equity = cash + Σ qty*price; update self.equity")
