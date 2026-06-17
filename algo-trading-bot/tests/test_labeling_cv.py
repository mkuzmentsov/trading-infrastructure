"""Tests for triple-barrier labeling, purged CV (no-leakage), and the meta-label flow."""

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Bar, Symbol, VenueId
from algo_trading_bot.features.dataset import FEATURE_COLUMNS, build_labeled_dataset
from algo_trading_bot.features.labeling import concurrency_weights, triple_barrier_labels
from algo_trading_bot.validation.purged_cv import PurgedKFold


def test_triple_barrier_hits_take_profit_and_stop():
    idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    # rises 1% per bar -> a long take-profit at +1 vol (vol=0.01) is hit on bar 1
    up = pd.Series([100 * (1.01**i) for i in range(10)], index=idx)
    vol = pd.Series(0.01, index=idx)
    labs = triple_barrier_labels(up, idx[:1], (1.0, 1.0), timedelta(hours=5),
                                 Symbol("BTC"), target_vol=vol, sides=pd.Series(1.0, index=idx))
    assert labs[0].outcome == 1 and labs[0].meta["correct"] == 1

    down = pd.Series([100 * (0.99**i) for i in range(10)], index=idx)
    labs2 = triple_barrier_labels(down, idx[:1], (1.0, 1.0), timedelta(hours=5),
                                  Symbol("BTC"), target_vol=vol, sides=pd.Series(1.0, index=idx))
    assert labs2[0].outcome == -1 and labs2[0].meta["correct"] == 0  # long was wrong


def test_concurrency_weights_lower_when_overlapping():
    idx = pd.date_range("2024-01-01", periods=20, freq="h", tz="UTC")
    prices = pd.Series(np.linspace(100, 110, 20), index=idx)
    vol = pd.Series(0.02, index=idx)
    labs = triple_barrier_labels(prices, idx[:5], (5.0, 5.0), timedelta(hours=6),
                                 Symbol("BTC"), target_vol=vol, sides=pd.Series(1.0, index=idx))
    w = concurrency_weights(labs, prices)
    assert len(w) == len(labs)
    assert all(0.0 < x <= 1.0 for x in w)  # overlapping vertical-barrier labels -> <1


def test_purged_kfold_purges_overlap_and_embargo():
    idx = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
    X = pd.DataFrame({"f": np.arange(100)}, index=idx)
    spans = pd.Series(idx + pd.Timedelta(hours=3), index=idx)  # each label spans 3 bars
    cv = PurgedKFold(n_splits=5, embargo_pct=0.05)
    for tr, te in cv.split(X, spans):
        assert len(set(tr) & set(te)) == 0                      # no overlap
        te_lo, te_hi = te.min(), te.max()
        for i in tr:
            # purged: a train label ending inside the test block must not survive
            assert not (i < te_lo and (idx.get_loc(spans.iloc[i]) >= te_lo))
            assert not (te_hi < i <= te_hi + 5)                 # embargo region empty


def _synthetic_bars(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    price, t0, bars = 30000.0, datetime(2024, 1, 1, tzinfo=timezone.utc), []
    for i in range(n):
        price *= math.exp(0.0004 + rng.normal(0, 0.012))
        ts = t0 + timedelta(hours=i + 1)
        bars.append(Bar(Symbol("BTC"), ts, price, price * 1.003, price * 0.997,
                        price, 100.0, VenueId("test"), knowable_at=ts))
    return bars


def test_build_labeled_dataset_shapes():
    X, y, w, spans = build_labeled_dataset(_synthetic_bars(), fast=20, slow=100,
                                           vol_window=48, vertical_bars=24)
    assert list(X.columns) == FEATURE_COLUMNS
    assert len(X) == len(y) == len(w) == len(spans) > 200
    assert set(y.unique()) <= {0, 1}
    assert X.notna().all().all()                                # no NaN features (warm only)


def test_meta_label_oos_auc_runs():
    from algo_trading_bot.model.metalabel import train_meta_label_cv

    X, y, w, spans = build_labeled_dataset(_synthetic_bars(2000), vertical_bars=24)
    res = train_meta_label_cv(X, y, w, spans, n_splits=4, mda_repeats=1)
    assert 0.0 <= res.oos_auc <= 1.0
    assert res.n_samples > 100
    assert len(res.importances) == res.n_features


def test_shuffled_labels_collapse_to_chance():
    """No-leak guard: with labels shuffled, a leak-free purged-CV harness must score
    ~0.5 OOS. If this rises, the CV is leaking (the most important regression to catch)."""
    from algo_trading_bot.model.metalabel import train_meta_label_cv

    X, y, w, spans = build_labeled_dataset(_synthetic_bars(2000), vertical_bars=24)
    rng = np.random.default_rng(0)
    y_shuf = pd.Series(rng.permutation(y.to_numpy()), index=y.index)
    res = train_meta_label_cv(X, y_shuf, w, spans, n_splits=4, mda_repeats=1)
    assert abs(res.oos_auc - 0.5) < 0.1
