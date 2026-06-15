"""Tier-1 volatility breakout (§6.2).

Enter on range breaks confirmed by volatility expansion. Trend-family, positive
skew. Core trend exposure; the regime gate turns it OFF in dead ranges.
"""

from __future__ import annotations

from ..core.types import Forecast, RiskTier
from .base import BaseStrategy, MarketState


class VolatilityBreakout(BaseStrategy):
    def __init__(self, lookback: int = 55, vol_mult: float = 1.5, id: str = "vol_breakout") -> None:
        super().__init__(id=id, tier=RiskTier.FOUNDATION)
        self.lookback = lookback
        self.vol_mult = vol_mult

    def on_data(self, state: MarketState) -> Forecast | None:
        raise NotImplementedError(
            "long when close breaks N-bar high AND realized vol expands > vol_mult*baseline; "
            "symmetric short on N-bar low break."
        )
