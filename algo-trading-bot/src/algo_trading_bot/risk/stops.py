"""Stops mapped from the triple-barrier exits used in training (§2.5, §5).

The stop a position carries live must be the SAME barrier the model was trained
against (§2.2 labeling), or backtest and live diverge. A stop hit is a risk event
with absolute precedence — it flattens the affected exposure immediately,
regardless of any strategy forecast (§7.2, §7.3 "if B is a risk/stop signal").

Design note (a real tension to resolve): §7 nets forecasts into a continuous book
with no discrete "positions", but stops are naturally per-entry. v0.1 resolves this
by mapping stops onto *net book exposure per instrument*: a stop level is tracked
against the net position's volume-weighted entry, and tripping it forces the target
for that instrument to flat until the regime/forecast re-establishes it. See
docs/ARCHITECTURE.md "Stops vs. forecast netting".
"""

from __future__ import annotations

from ..core.types import Position, Symbol, TargetPosition


class StopManager:
    def __init__(self, pt_sl: tuple[float, float]) -> None:
        self.pt_sl = pt_sl  # same (take-profit, stop-loss) widths as the labels
        self._stops: dict[Symbol, float] = {}

    def on_fill(self, position: Position, ref_vol: float) -> None:
        """(Re)compute the stop level for an instrument from its net entry + vol."""
        raise NotImplementedError("stop = entry -/+ sl*ref_vol depending on side")

    def check(self, symbol: Symbol, last_price: float) -> TargetPosition | None:
        """If price has breached the stop, return a flat target (absolute precedence)."""
        raise NotImplementedError("if breached: return TargetPosition(symbol, 0.0, reason='stop')")
