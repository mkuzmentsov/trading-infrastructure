"""Regime classifier tests (§2.4).

Covers the two feature primitives (Kaufman efficiency ratio, vol percentile) and the
TrendRangeDetector's classification + the gate's effect on a FOUNDATION trend forecast.
"""

import math
from datetime import datetime, timedelta, timezone

from algo_trading_bot.arbitration.regime import (
    HysteresisDetector,
    RegimeGate,
    TrendRangeDetector,
    _soft_trend_weight,
)
from algo_trading_bot.core.types import (
    Bar,
    Forecast,
    Regime,
    RiskTier,
    StrategyId,
    Symbol,
    VenueId,
)
from algo_trading_bot.features.pipeline import (
    RollingFeaturePipeline,
    _efficiency_ratio,
    _percentile_rank,
)


def test_efficiency_ratio_extremes():
    # a perfectly straight line -> ER == 1 (net move == path length)
    straight = [100, 101, 102, 103, 104, 105]
    assert _efficiency_ratio(straight, 5) == 1.0
    # a round trip that returns to start -> ER == 0 (net move == 0)
    roundtrip = [100, 105, 100, 105, 100, 100]
    assert _efficiency_ratio(roundtrip, 5) == 0.0
    # not enough history yet
    assert _efficiency_ratio([100, 101], 5) == 0.0


def test_percentile_rank():
    hist = [1.0, 2.0, 3.0, 4.0]
    assert _percentile_rank(hist, 4.0) == 1.0     # >= all
    assert _percentile_rank(hist, 2.0) == 0.5     # >= two of four
    assert _percentile_rank(hist, 0.5) == 0.0     # below all
    assert _percentile_rank([], 1.0) == 0.5       # empty -> neutral


def test_detector_unknown_until_ready():
    det = TrendRangeDetector()
    assert det.detect({"regime_ready": 0.0, "efficiency_ratio": 0.9}) is Regime.UNKNOWN


def test_detector_classifies_each_regime():
    det = TrendRangeDetector(er_trend=0.30, vol_pct_high=0.90)
    base = {"regime_ready": 1.0, "ema_fast": 110.0, "ema_slow": 100.0}
    # high vol wins regardless of trend strength
    assert det.detect({**base, "vol_pct": 0.95, "efficiency_ratio": 0.99}) is Regime.HIGH_VOL
    # strong ER + fast>slow -> trend up
    assert det.detect({**base, "vol_pct": 0.5, "efficiency_ratio": 0.5}) is Regime.TREND_UP
    # strong ER + fast<slow -> trend down
    assert det.detect({**base, "ema_fast": 90.0, "vol_pct": 0.5, "efficiency_ratio": 0.5}) is Regime.TREND_DOWN
    # weak ER, normal vol -> range
    assert det.detect({**base, "vol_pct": 0.5, "efficiency_ratio": 0.1}) is Regime.RANGE


def test_gate_zeroes_foundation_in_range():
    gate = RegimeGate(TrendRangeDetector())
    fc = Forecast(strategy=StrategyId("trend"), symbol=Symbol("BTC"),
                  ts=datetime(2024, 1, 1, tzinfo=timezone.utc), value=0.8)
    # trend (FOUNDATION) passes in a trend, is zeroed in a range
    assert gate.apply(fc, RiskTier.FOUNDATION, Regime.TREND_UP).value == 0.8
    assert gate.apply(fc, RiskTier.FOUNDATION, Regime.RANGE).value == 0.0
    assert gate.apply(fc, RiskTier.FOUNDATION, Regime.HIGH_VOL).value == 0.0


class _Fixed:
    def __init__(self, seq):
        self.seq, self.i = seq, 0

    def detect(self, features):
        r = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return r


def test_hysteresis_debounces_flicker():
    # one warmup bar to confirm the initial regime, then a single-bar flip to RANGE inside a
    # TREND_UP run must NOT switch the reported regime (transient never persists `persist` bars)
    seq = [Regime.TREND_UP, Regime.TREND_UP, Regime.RANGE, Regime.TREND_UP, Regime.TREND_UP]
    det = HysteresisDetector(_Fixed(seq), persist=2)
    out = [det.detect({}) for _ in seq]
    assert out == [Regime.UNKNOWN, Regime.TREND_UP, Regime.TREND_UP, Regime.TREND_UP, Regime.TREND_UP]
    assert Regime.RANGE not in out                 # the transient RANGE was debounced away

    # a sustained switch DOES flip after `persist` consecutive bars
    seq2 = [Regime.TREND_UP, Regime.RANGE, Regime.RANGE, Regime.RANGE]
    det2 = HysteresisDetector(_Fixed(seq2), persist=2)
    out2 = [det2.detect({}) for _ in seq2]
    assert out2 == [Regime.UNKNOWN, Regime.UNKNOWN, Regime.RANGE, Regime.RANGE]


def test_soft_trend_weight_ramps_with_efficiency():
    # below er_lo -> 0, above er_hi -> 1, linear between; high vol cuts it
    assert _soft_trend_weight({"efficiency_ratio": 0.10}, 0.15, 0.45, 0.90) == 0.0
    assert _soft_trend_weight({"efficiency_ratio": 0.45}, 0.15, 0.45, 0.90) == 1.0
    mid = _soft_trend_weight({"efficiency_ratio": 0.30}, 0.15, 0.45, 0.90)
    assert abs(mid - 0.5) < 1e-9
    # strong trend but extreme vol -> weight cut toward 0
    assert _soft_trend_weight({"efficiency_ratio": 0.45, "vol_pct": 1.0}, 0.15, 0.45, 0.90) == 0.0


def test_soft_gate_scales_foundation_continuously():
    gate = RegimeGate(TrendRangeDetector(), mode="soft", soft_er_lo=0.15, soft_er_hi=0.45)
    fc = Forecast(strategy=StrategyId("trend"), symbol=Symbol("BTC"),
                  ts=datetime(2024, 1, 1, tzinfo=timezone.utc), value=0.8)
    feats = {"efficiency_ratio": 0.30, "vol_pct": 0.5}     # mid ER -> ~0.5 weight
    out = gate.apply(fc, RiskTier.FOUNDATION, Regime.RANGE, feats)
    assert abs(out.value - 0.4) < 1e-9                      # 0.8 * 0.5, NOT a hard zero


def test_pipeline_emits_regime_features_when_warm():
    import numpy as np
    rng = np.random.default_rng(0)
    pipe = RollingFeaturePipeline(fast=5, slow=20, vol_window=10, er_window=10, vol_pct_min=10)
    price, t0 = 100.0, datetime(2024, 1, 1, tzinfo=timezone.utc)
    feats = {}
    for i in range(120):
        price *= math.exp(0.003 + rng.normal(0, 0.0005))  # steady uptrend, small noise -> vol>0
        ts = t0 + timedelta(hours=i + 1)
        feats = pipe.update(Bar(Symbol("BTC"), ts, price, price, price, price, 1.0, VenueId("t"), knowable_at=ts))
    assert feats["regime_ready"] == 1.0
    assert 0.0 <= feats["vol_pct"] <= 1.0
    # a steady uptrend should read as highly efficient (strong trend)
    assert feats["efficiency_ratio"] > 0.9
