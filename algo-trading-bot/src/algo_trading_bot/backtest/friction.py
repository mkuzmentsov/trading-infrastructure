"""Realistic friction — non-optional (§3.2).

The fill simulator is the backtest's execution adapter. It must model, at minimum:
maker/taker fees with tiers; funding at real settlement times; size/liquidity-scaled
slippage; signal-to-fill latency; borrow/margin costs. Underestimated costs are, with
overfitting, the #1 cause of bots that look great in a notebook and die live (§11).
"""

from __future__ import annotations

from ..config import FrictionConfig
from ..core.types import Fill, Order, Position, Symbol


class FillSimulator:
    """Execution adapter used in backtest. Implements the ExecutionAdapter protocol."""

    def __init__(self, friction: FrictionConfig) -> None:
        self.friction = friction
        self._positions: dict[Symbol, Position] = {}

    def place(self, order: Order) -> None:
        raise NotImplementedError(
            "apply latency (fill at price `latency_ms` later), size-scaled slippage, "
            "maker/taker fee; emit Fill(s) including partials."
        )

    def cancel(self, client_id: str) -> None:
        raise NotImplementedError

    def open_orders(self) -> list[Order]:
        return []

    def positions(self) -> dict[Symbol, Position]:
        return self._positions

    def poll_fills(self) -> list[Fill]:
        raise NotImplementedError

    def apply_funding(self, position: Position, funding_rate: float) -> float:
        """Charge/credit funding at settlement (§3.2). Returns the cash flow."""
        raise NotImplementedError("funding = -position.notional * funding_rate")
