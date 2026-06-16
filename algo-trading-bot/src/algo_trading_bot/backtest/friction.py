"""Realistic friction — non-optional (§3.2).

The fill simulator is the backtest's execution adapter. It must model, at minimum:
maker/taker fees with tiers; funding at real settlement times; size/liquidity-scaled
slippage; signal-to-fill latency; borrow/margin costs. Underestimated costs are, with
overfitting, the #1 cause of bots that look great in a notebook and die live (§11).
"""

from __future__ import annotations

from ..config import FrictionConfig
from ..core.types import Fill, Order, Position, Side, Symbol


class FillSimulator:
    """Execution adapter used in backtest. Implements the ExecutionAdapter protocol.

    v0.1 model: market orders fill at the current bar's close marked-price, plus
    size-aware slippage and the taker fee. Signal-to-fill latency is negligible at
    swing/position bar sizes (1h/1d) so it is folded into slippage rather than
    simulated tick-by-tick. Partial fills, queue position, and funding settlement are
    follow-ups (§3.2) — flagged here, not silently omitted.
    """

    # crude size-impact: extra slippage (bps) per $1M of notional traded.
    _IMPACT_BPS_PER_MM = 1.0

    def __init__(self, friction: FrictionConfig) -> None:
        self.friction = friction
        self._marks: dict[Symbol, float] = {}
        self._fills: list[Fill] = []

    def update_market(self, symbol: Symbol, price: float, ts=None) -> None:
        """Engine pushes the latest marked price each bar; fills reference it."""
        self._marks[symbol] = price
        self._last_ts = ts

    def place(self, order: Order) -> None:
        mark = self._marks.get(order.symbol)
        if mark is None or mark <= 0:
            return
        notional = order.quantity * mark
        slip_bps = self.friction.taker_fee_bps + self._IMPACT_BPS_PER_MM * (notional / 1_000_000)
        sign = 1.0 if order.side == Side.LONG else -1.0
        fill_price = mark * (1 + sign * slip_bps / 10_000)
        fee = notional * self.friction.taker_fee_bps / 10_000
        self._fills.append(
            Fill(
                order_id=order.client_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=fill_price,
                fee=fee,
                ts=order.ts or self._last_ts,
                venue=order.venue,
                is_maker=False,
            )
        )

    def cancel(self, client_id: str) -> None:
        return  # market orders fill instantly in this model; nothing to cancel

    def open_orders(self) -> list[Order]:
        return []

    def positions(self) -> dict[Symbol, Position]:
        return {}  # positions are owned by the engine portfolio in backtest

    def poll_fills(self) -> list[Fill]:
        fills, self._fills = self._fills, []
        return fills

    def apply_funding(self, position: Position, funding_rate: float) -> float:
        """Charge/credit funding at settlement (§3.2). Returns the cash flow."""
        return -position.quantity * funding_rate
