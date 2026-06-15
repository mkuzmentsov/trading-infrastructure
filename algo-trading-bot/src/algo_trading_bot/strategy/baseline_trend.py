"""Tier-1 time-series (trend) momentum — THE BENCHMARK (§6.1, §6.2).

This is the dumb directional baseline. Build it first; every ML model must beat it
OOS, after costs, or it does not ship (principle #4). Positive skew, lower blow-up
risk, bleeds in chop — largest risk budget.

Classic form: forecast = scaled, vol-normalized trend (e.g. fast/slow EMA
crossover or breakout of an N-day high), clipped to [-1, +1].
"""

from __future__ import annotations

from ..core.types import Forecast, RiskTier
from .base import BaseStrategy, MarketState


class TrendMomentum(BaseStrategy):
    def __init__(self, fast: int = 20, slow: int = 100, id: str = "trend_momentum") -> None:
        super().__init__(id=id, tier=RiskTier.FOUNDATION)
        self.fast = fast
        self.slow = slow

    def on_data(self, state: MarketState) -> Forecast | None:
        raise NotImplementedError(
            "forecast = clip(vol_normalized(fast_ema - slow_ema), -1, 1); "
            "set valid_until per bar interval (§7.5)."
        )
