"""Forecast combiner — the heart of §7 (Carver combined-forecast approach).

Strategies do not fight as discrete events. Each emits a continuous forecast; the
combiner nets them, per instrument, into ONE combined forecast. A new opposite
signal does not "cancel" an open trade — it changes the combined forecast, hence the
target, and the book moves toward the new target (§7.1, §7.3).

Precedence (§7.2), highest first:
  1. Risk layer (absolute) — applied downstream in risk/, not here.
  2. Regime gate — already zeroed ineligible forecasts before they arrive here.
  3. Weighted netting — weight = validated_edge x live_confidence x risk_budget.
     "Higher precedence" == higher weight, NOT a hard override.

Stale forecasts decay toward zero (§7.5) before they are weighted.
"""

from __future__ import annotations

from datetime import datetime

from ..core.types import Forecast, StrategyId, Symbol


class ForecastCombiner:
    def __init__(self, weights: dict[StrategyId, float] | None = None) -> None:
        # weight = validated_edge_quality * risk_budget; live_confidence multiplies per-forecast.
        self.weights = weights or {}

    def combine(self, forecasts: list[Forecast], now: datetime) -> dict[Symbol, float]:
        """Net per-symbol forecasts into a single combined forecast in [-1, +1]."""
        num: dict[Symbol, float] = {}
        den: dict[Symbol, float] = {}
        for fc in forecasts:
            w = self.weights.get(fc.strategy, 1.0) * fc.confidence * self.staleness_decay(fc, now)
            if w == 0:
                continue
            num[fc.symbol] = num.get(fc.symbol, 0.0) + w * fc.value
            den[fc.symbol] = den.get(fc.symbol, 0.0) + abs(w)
        out: dict[Symbol, float] = {}
        for sym, d in den.items():
            if d > 0:
                out[sym] = max(-1.0, min(1.0, num[sym] / d))
        return out

    @staticmethod
    def staleness_decay(forecast: Forecast, now: datetime) -> float:
        """Multiplier in [0, 1]: 1 while fresh, linearly decaying to 0 over one extra
        validity window past ``valid_until`` (§7.5)."""
        if forecast.valid_until is None or now <= forecast.valid_until:
            return 1.0
        window = forecast.valid_until - forecast.ts
        if window.total_seconds() <= 0:
            return 0.0
        overshoot = (now - forecast.valid_until).total_seconds() / window.total_seconds()
        return max(0.0, 1.0 - overshoot)
