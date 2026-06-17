"""Tests for CSCV-based PBO and the combinatorial purged splitter (§4.2)."""

import numpy as np
import pandas as pd

from algo_trading_bot.validation.cpcv import CombinatorialPurgedCV, cscv_pbo


def _matrix(n_trials, T=600, seed=0, signal_col=None):
    rng = np.random.default_rng(seed)
    cols = {}
    for j in range(n_trials):
        mu = 0.0
        if signal_col is not None and j == signal_col:
            mu = 0.002  # one genuinely better trial (consistent IS and OOS)
        cols[f"t{j}"] = rng.normal(mu, 0.01, T)
    return pd.DataFrame(cols, index=pd.date_range("2022-01-01", periods=T, freq="D", tz="UTC"))


def test_pbo_high_for_pure_noise():
    """All trials are noise -> the IS-best is luck -> PBO should be high (~0.5)."""
    res = cscv_pbo(_matrix(12, seed=1), n_blocks=10)
    assert res.n_trials == 12
    assert res.pbo > 0.35           # noise selection does not generalize
    assert 0.0 <= res.pbo <= 1.0


def test_pbo_low_when_one_trial_truly_dominates():
    """One trial has a real, persistent edge -> IS-best generalizes -> low PBO."""
    res = cscv_pbo(_matrix(12, seed=2, signal_col=3), n_blocks=10)
    assert res.pbo < 0.2
    assert res.median_oos_sharpe > 0


def test_pbo_handles_degenerate_input():
    res = cscv_pbo(_matrix(1), n_blocks=10)   # <2 trials
    assert np.isnan(res.pbo)


def test_combinatorial_purged_cv_paths_and_no_overlap():
    idx = pd.date_range("2022-01-01", periods=120, freq="D", tz="UTC")
    X = pd.DataFrame({"f": np.arange(120)}, index=idx)
    spans = pd.Series(idx + pd.Timedelta(days=2), index=idx)
    cv = CombinatorialPurgedCV(n_groups=6, n_test_groups=2, embargo_pct=0.0)
    n = 0
    for tr, te in cv.split(X, spans):
        assert len(set(tr) & set(te)) == 0
        n += 1
    from math import comb
    assert n == comb(6, 2)                 # one split per group-combination
    assert cv.n_paths() == comb(6, 2) * 2 // 6
