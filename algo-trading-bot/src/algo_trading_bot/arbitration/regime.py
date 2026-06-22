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


class HysteresisDetector:
    """Debounce wrapper: only switch the reported regime once a new one has persisted for
    ``persist`` consecutive bars. Kills the flicker that whipsaws a hard gate (experiment #1
    finding). State is single-book (these configs trade one symbol); a multi-symbol engine
    would key this per symbol."""

    def __init__(self, inner: RegimeDetector, persist: int = 3) -> None:
        self.inner = inner
        self.persist = max(1, persist)
        self._current: Regime = Regime.UNKNOWN
        self._candidate: Regime = Regime.UNKNOWN
        self._count: int = 0

    def detect(self, features: dict[str, float]) -> Regime:
        raw = self.inner.detect(features)
        if raw == self._current:
            self._candidate, self._count = raw, 0
            return self._current
        if raw == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = raw, 1
        if self._count >= self.persist:
            self._current, self._count = self._candidate, 0
        return self._current


def _soft_trend_weight(features: dict[str, float], er_lo: float, er_hi: float,
                       vol_pct_high: float) -> float:
    """Continuous trend weight in [0,1] for the FOUNDATION tier: ramps with the efficiency
    ratio (chop->trend) and is cut in the top vol bucket. Smooth, so no flatten/reopen churn."""
    er = features.get("efficiency_ratio", 0.0)
    w = (er - er_lo) / (er_hi - er_lo) if er_hi > er_lo else (1.0 if er >= er_hi else 0.0)
    w = 0.0 if w < 0.0 else 1.0 if w > 1.0 else w
    vp = features.get("vol_pct", 0.0)
    if vp >= vol_pct_high:                         # linearly cut from 1.0 at the threshold to 0 at 1.0
        cut = (vp - vol_pct_high) / max(1.0 - vol_pct_high, 1e-6)
        w *= max(0.0, 1.0 - cut)
    return w


class RegimeGate:
    """Gate the forecast by regime. ``mode``:
      - ``hard``       : zero the forecast if its tier isn't permitted in the regime (original).
      - ``hysteresis`` : same on/off rule, but on a debounced regime (wrap detector upstream).
      - ``soft``       : scale the FOUNDATION forecast by a continuous ER-derived trend weight
                         instead of a 0/1 switch — removes the flicker churn.
    """

    def __init__(self, detector: RegimeDetector, mode: str = "hard",
                 soft_er_lo: float = 0.15, soft_er_hi: float = 0.45,
                 vol_pct_high: float = 0.90) -> None:
        self.detector = detector
        self.mode = mode
        self.soft_er_lo = soft_er_lo
        self.soft_er_hi = soft_er_hi
        self.vol_pct_high = vol_pct_high

    def apply(self, forecast: Forecast, tier: RiskTier, regime: Regime,
              features: dict[str, float] | None = None) -> Forecast:
        """Return the forecast scaled/zeroed for ``regime``. Never flips sign — gating only
        removes risk. ``soft`` mode needs ``features`` (ER/vol_pct); falls back to hard if absent."""
        if self.mode == "soft" and features is not None and regime != Regime.UNKNOWN:
            if tier == RiskTier.FOUNDATION:
                w = _soft_trend_weight(features, self.soft_er_lo, self.soft_er_hi, self.vol_pct_high)
                return forecast if w >= 1.0 else replace(forecast, value=forecast.value * w)
            return forecast
        if tier in _GATE.get(regime, set()):
            return forecast
        return replace(forecast, value=0.0)


def make_regime_gate(cfg) -> RegimeGate:
    """Build the regime gate from a RegimeConfig: detector (optionally hysteresis-wrapped) + mode."""
    detector: RegimeDetector = TrendRangeDetector(er_trend=cfg.er_trend, vol_pct_high=cfg.vol_pct_high)
    if cfg.mode == "hysteresis":
        detector = HysteresisDetector(detector, persist=cfg.persist)
    return RegimeGate(detector, mode=cfg.mode, soft_er_lo=cfg.soft_er_lo,
                      soft_er_hi=cfg.soft_er_hi, vol_pct_high=cfg.vol_pct_high)
