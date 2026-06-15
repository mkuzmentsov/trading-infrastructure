"""Forecast combiner — the heart of §7 (Carver combined-forecast approach).

Strategies do not fight as discrete events. Each emits a continuous forecast; the
combiner nets them, per instrument, into ONE target position. A new opposite signal
does not "cancel" an open trade — it changes the combined forecast, hence the
target, and the book moves toward the new target (§7.1, §7.3).

Precedence (§7.2), highest first:
  1. Risk layer (absolute) — applied downstream in risk/, not here.
  2. Regime gate — already zeroed ineligible forecasts before they arrive here.
  3. Weighted netting — weight = validated_edge x live_confidence x risk_budget.
     "Higher precedence" == higher weight, NOT a hard override.

This module also applies the §7.5 practical guards: stale forecasts decay toward
zero, and sub-threshold target changes are absorbed by a deadband (hysteresis) so
the book doesn't whipsaw and bleed fees near a flip point. The deadband is
transaction-cost hygiene only — it never suppresses a genuine reversal (§7.4).
"""

from __future__ import annotations

from datetime import datetime

from ..core.types import Forecast, StrategyId, Symbol


class ForecastCombiner:
    def __init__(self, weights: dict[StrategyId, float]) -> None:
        # weight = validated_edge_quality * risk_budget; live_confidence multiplies per-forecast.
        self.weights = weights

    def combine(self, forecasts: list[Forecast], now: datetime) -> dict[Symbol, float]:
        """Net per-symbol forecasts into a single combined forecast in ~[-1, +1].

        Steps: decay stale forecasts toward zero (§7.5); multiply each by
        weight * confidence; sum per symbol; normalize by total weight; clip.
        """
        raise NotImplementedError(
            "group by symbol; w_i = self.weights[f.strategy] * f.confidence * staleness_decay(f, now); "
            "combined = clip(sum(w_i * f.value) / sum(|w_i|), -1, 1)."
        )

    @staticmethod
    def staleness_decay(forecast: Forecast, now: datetime) -> float:
        """Multiplier in [0, 1]: 1 while fresh, decaying to 0 past valid_until (§7.5)."""
        raise NotImplementedError("linear/exptl decay from valid_until")
