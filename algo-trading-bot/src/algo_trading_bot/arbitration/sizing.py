"""Sizing: forecast strength -> notional, under vol-targeting and a Kelly cap (§2.4, §5).

Two jobs:
1. **Volatility targeting** — scale total exposure so the book runs at a target
   annualized vol; auto-shrink when realized vol spikes (§2.4). This is the single
   most important survival lever after stops.
2. **Confidence-scaled, fraction-of-Kelly sizing** — a combined forecast in
   [-1, +1] maps to a notional, capped at <= half-Kelly and at hard leverage limits
   (§5). Risk has the final say in risk/limits.py.
"""

from __future__ import annotations

from ..config import RiskConfig
from ..core.types import Symbol, TargetPosition


class VolTargetSizer:
    def __init__(self, risk: RiskConfig, capital_quote: float) -> None:
        self.risk = risk
        self.capital = capital_quote

    def size(
        self,
        symbol: Symbol,
        combined_forecast: float,
        realized_vol: float,
        ts,
    ) -> TargetPosition:
        """Map a netted forecast to a signed target notional.

        notional ~= forecast * (target_vol / realized_vol) * capital * kelly_fraction,
        then clamped to leverage and per-instrument caps. Higher realized_vol -> smaller
        position (vol targeting). Risk layer may shrink further; it never grows this.
        """
        raise NotImplementedError(
            "scale by target_vol/realized_vol, apply kelly_fraction, clamp to "
            "max_gross_leverage and max_position_notional."
        )
