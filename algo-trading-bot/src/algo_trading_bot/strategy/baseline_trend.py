"""Tier-1 time-series (trend) momentum — THE BENCHMARK (§6.1, §6.2).

This is the dumb directional baseline. Build it first; every ML model must beat it
OOS, after costs, or it does not ship (principle #4). Positive skew, lower blow-up
risk, bleeds in chop — largest risk budget.

Forecast = vol-normalized EMA(fast) - EMA(slow), squashed into [-1, +1]. Dividing
the trend by volatility is what makes the forecast comparable across regimes and
across instruments (Carver). It abstains until features are warm.
"""

from __future__ import annotations

import math
from datetime import timedelta

from ..core.types import Forecast, RiskTier, StrategyId
from .base import BaseStrategy, MarketState

# Bar interval -> validity window for the forecast (§7.5). A trend read is good for
# about one bar; past that the combiner decays it toward zero.
_VALIDITY = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class TrendMomentum(BaseStrategy):
    def __init__(self, interval: str = "1h", scale: float = 10.0, id: str = "trend_momentum") -> None:
        super().__init__(id=id, tier=RiskTier.FOUNDATION)
        self.interval = interval
        self.scale = scale  # maps the dimensionless trend/vol ratio into ~[-1, 1] via tanh

    def on_data(self, state: MarketState) -> Forecast | None:
        f = state.features
        if not f or f.get("ready", 0.0) < 1.0:
            return None
        close = f["close"]
        ret_vol = f["ret_vol"]
        if ret_vol <= 0 or close <= 0:
            return None

        # Trend as a fraction of price, normalized by per-bar volatility -> unit-free.
        trend = (f["ema_fast"] - f["ema_slow"]) / close
        raw = trend / ret_vol
        value = math.tanh(raw / self.scale)  # smooth clip to (-1, 1)

        valid_for = timedelta(minutes=_VALIDITY.get(self.interval, 60))
        return Forecast(
            strategy=StrategyId(self.id),
            symbol=state.latest_bar.symbol,
            ts=state.latest_bar.ts,
            value=value,
            confidence=1.0,
            valid_until=state.latest_bar.ts + valid_for,
        )
