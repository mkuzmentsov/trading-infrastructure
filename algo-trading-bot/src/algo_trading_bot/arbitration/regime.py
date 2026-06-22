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
    """Classify TREND_UP / TREND_DOWN / RANGE / HIGH_VOL from causal regime features.

    Two orthogonal axes, both supplied by ``RollingFeaturePipeline``:
      - trend strength: Kaufman ``efficiency_ratio`` (≈1 clean trend, ≈0 chop).
      - volatility state: ``vol_pct`` — percentile of current realized vol vs its trailing
        distribution.

    Decision (precedence top-down):
      1. ``vol_pct >= vol_pct_high``                  -> HIGH_VOL  (de-risk everything but CORE)
      2. ``efficiency_ratio >= er_trend``             -> TREND_UP / TREND_DOWN by EMA-spread sign
      3. otherwise                                    -> RANGE     (gates the FOUNDATION trend off)

    Thresholds are fixed a-priori from convention (NOT tuned on the test set) to keep the
    overfitting surface small — ER 0.30 is the usual Kaufman trend cutoff; vol_pct 0.90 flags
    the top decile of realized vol. Returns UNKNOWN until ``regime_ready`` (warmup), which
    permits the trend baseline through, matching prior behavior during warmup.
    """

    def __init__(self, er_trend: float = 0.30, vol_pct_high: float = 0.90) -> None:
        self.er_trend = er_trend
        self.vol_pct_high = vol_pct_high

    def detect(self, features: dict[str, float]) -> Regime:
        if features.get("regime_ready", 0.0) < 1.0:
            return Regime.UNKNOWN
        if features.get("vol_pct", 0.0) >= self.vol_pct_high:
            return Regime.HIGH_VOL
        if features.get("efficiency_ratio", 0.0) >= self.er_trend:
            trending_up = features.get("ema_fast", 0.0) >= features.get("ema_slow", 0.0)
            return Regime.TREND_UP if trending_up else Regime.TREND_DOWN
        return Regime.RANGE


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
