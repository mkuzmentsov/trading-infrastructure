"""Regime detection + gate (§2.4, §6.2, §7.2).

A trend model bleeds in a range; a mean-reversion model dies in a trend
(principle #8). The gate detects the current regime and can ZERO OUT a strategy's
forecast entirely (§7.2 precedence rank 2 — below the risk layer, above netting).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ..core.types import Forecast, Regime, RiskTier


class RegimeDetector(Protocol):
    def detect(self, features: dict[str, float]) -> Regime: ...


class TrendRangeDetector:
    """Reference detector: classify TREND_* vs RANGE vs HIGH_VOL from features such
    as ADX, realized-vol percentile, Hurst exponent, efficiency ratio."""

    def detect(self, features: dict[str, float]) -> Regime:
        # v0.1: no regime classifier yet -> UNKNOWN, which permits the Tier-1 trend
        # baseline through the gate. A real ADX/Hurst/efficiency-ratio classifier
        # replaces this when the regime-gate slice lands.
        return Regime.UNKNOWN


# Which tiers are permitted in which regime. Tactical (mean-reversion) is gated OFF
# in trends; foundation (trend/breakout) is gated OFF in ranges. High vol shrinks all
# (handled by vol targeting in sizing.py), but tactical is also blocked outright.
_GATE: dict[Regime, set[RiskTier]] = {
    Regime.TREND_UP: {RiskTier.FOUNDATION, RiskTier.CORE},
    Regime.TREND_DOWN: {RiskTier.FOUNDATION, RiskTier.CORE},
    Regime.RANGE: {RiskTier.CORE, RiskTier.TACTICAL},
    Regime.HIGH_VOL: {RiskTier.CORE},
    Regime.UNKNOWN: {RiskTier.FOUNDATION, RiskTier.CORE},
}


class RegimeGate:
    def __init__(self, detector: RegimeDetector) -> None:
        self.detector = detector

    def apply(self, forecast: Forecast, tier: RiskTier, regime: Regime) -> Forecast:
        """Return the forecast unchanged if its tier is permitted in ``regime``,
        else a zeroed copy. Never flips sign — gating only removes risk."""
        if tier in _GATE.get(regime, set()):
            return forecast
        return replace(forecast, value=0.0)
