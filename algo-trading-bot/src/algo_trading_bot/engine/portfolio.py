"""Portfolio accounting — cash + positions, maintained from fills.

The single source of truth for current exposure and NAV in both backtest and live
(NFR1). In live, it is reconciled against the venue on restart (NFR4); in backtest
it is updated from the FillSimulator's fills. Realized PnL is booked on reductions.
"""

from __future__ import annotations

from ..core.types import Fill, Position, Side, Symbol


class Portfolio:
    def __init__(self, starting_cash: float) -> None:
        self.cash = starting_cash
        self.positions: dict[Symbol, Position] = {}

    def position(self, symbol: Symbol) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def apply_fill(self, fill: Fill) -> float:
        """Update cash + position from a fill. Returns realized PnL booked by this fill."""
        pos = self.position(fill.symbol)
        signed_qty = fill.quantity if fill.side == Side.LONG else -fill.quantity

        # cash: pay for buys, receive for sells, always pay the fee.
        self.cash -= signed_qty * fill.price
        self.cash -= fill.fee

        realized = 0.0
        old_qty = pos.quantity
        new_qty = old_qty + signed_qty

        if old_qty == 0 or (old_qty > 0) == (signed_qty > 0):
            # opening or adding in the same direction -> volume-weighted average price
            total = abs(old_qty) + abs(signed_qty)
            pos.avg_price = (abs(old_qty) * pos.avg_price + abs(signed_qty) * fill.price) / total if total else 0.0
        else:
            # reducing/closing/flipping -> realize PnL on the closed portion
            closed = min(abs(signed_qty), abs(old_qty))
            direction = 1.0 if old_qty > 0 else -1.0
            realized = direction * closed * (fill.price - pos.avg_price)
            pos.realized_pnl += realized
            if abs(signed_qty) > abs(old_qty):  # flipped through zero
                pos.avg_price = fill.price

        pos.quantity = new_qty
        if new_qty == 0:
            pos.avg_price = 0.0
        return realized

    def equity(self, prices: dict[Symbol, float]) -> float:
        """Mark-to-market NAV = cash + Σ position notional at last known prices."""
        mtm = sum(p.quantity * prices.get(s, p.avg_price) for s, p in self.positions.items())
        return self.cash + mtm
