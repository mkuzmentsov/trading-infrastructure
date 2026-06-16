"""Sizing: forecast strength -> notional, under vol-targeting and a Kelly cap (§2.4, §5).

Two jobs:
1. **Volatility targeting** — scale exposure so the book runs at a target annualized
   vol; auto-shrink when realized vol spikes (§2.4). The single most important
   survival lever after stops.
2. **Confidence-scaled, fraction-of-Kelly sizing** — a combined forecast in [-1, +1]
   maps to a notional, capped at <= half-Kelly and at the hard leverage ceiling (§5).
   The risk layer (risk/limits.py) has the final say and can only shrink this.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..config import RiskConfig
from ..core.types import Symbol, TargetPosition


class VolTargetSizer:
    def __init__(self, risk: RiskConfig, capital_quote: float, periods_per_year: float) -> None:
        self.risk = risk
        self.capital = capital_quote
        self.periods_per_year = periods_per_year

    def size(
        self,
        symbol: Symbol,
        combined_forecast: float,
        realized_vol: float,  # per-bar stdev of log returns
        ts: datetime,
    ) -> TargetPosition:
        """Map a netted forecast to a signed target notional.

        notional = forecast * (target_vol / annualized_vol) * capital * kelly_fraction,
        clamped to the leverage ceiling and per-instrument cap. Higher realized vol ->
        smaller position (vol targeting).
        """
        ann_vol = realized_vol * math.sqrt(self.periods_per_year)
        if ann_vol <= 0 or self.capital <= 0:
            return TargetPosition(symbol=symbol, notional=0.0, ts=ts, reason="no-vol")

        vol_scalar = self.risk.target_annual_vol / ann_vol
        notional = combined_forecast * vol_scalar * self.capital * self.risk.kelly_fraction

        # Leverage ceiling (gross, single-instrument view) and optional hard cap.
        max_notional = self.capital * self.risk.max_gross_leverage
        if self.risk.max_position_notional > 0:
            max_notional = min(max_notional, self.risk.max_position_notional)
        notional = max(-max_notional, min(max_notional, notional))

        return TargetPosition(symbol=symbol, notional=notional, ts=ts, reason="vol_target")
