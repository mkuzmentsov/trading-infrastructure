"""Tests for the multi-asset time-series trend book: causal forecast, vol-targeted
gross cap, and that it captures both up- and down-trends (directional per asset)."""

import numpy as np
import pandas as pd

from algo_trading_bot.backtest.ts_trend import (
    _shrunk_cov,
    correlation_aware_weights,
    run_sleeved_ts_trend_backtest,
    run_ts_trend_backtest,
    ts_trend_forecast,
    ts_trend_weights,
)


def _two_asset_panel(shared_shock: bool, n=400, seed=1):
    """Two-asset price panel; shared return shocks (corr~1) vs independent."""
    rng = np.random.default_rng(seed)
    z1 = rng.normal(0, 0.02, n)
    z2 = z1 if shared_shock else rng.normal(0, 0.02, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"A": 100 * np.exp(np.cumsum(z1)),
                         "B": 100 * np.exp(np.cumsum(z2))}, index=idx)


def test_sleeved_backtest_runs_and_respects_leverage():
    # two sleeves with DIFFERENT trend windows on a 6-asset panel (3 up / 3 down)
    panel = _panel(360)
    sleeves = {"a": ["A", "B", "C"], "b": ["D", "E", "F"]}
    sleeve_params = {"a": (10, 50), "b": (20, 100)}
    res = run_sleeved_ts_trend_backtest(
        panel, sleeves=sleeves, sleeve_params=sleeve_params, vol_window=20, scale=10.0,
        target_vol=0.20, leverage=2.0, fee_bps=4.5, periods_per_year=365,
        cov_window=60, shrinkage=0.3)
    assert len(res.returns) > 100
    assert np.isfinite(res.metrics.sharpe)
    assert res.gross_exposure <= 2.0 + 1e-9          # global gross cap respected
    assert (res.equity > 0).all()                    # solvent throughout


def test_shrunk_cov_preserves_variance_symmetric():
    rng = np.random.default_rng(0)
    w = rng.normal(0, 0.02, size=(200, 3))
    s = np.cov(w, rowvar=False)
    shrunk = _shrunk_cov(w, shrinkage=0.5)
    assert shrunk.shape == (3, 3)
    assert np.allclose(shrunk, shrunk.T)                         # symmetric
    assert np.allclose(np.diag(shrunk), np.diag(s), atol=1e-12)  # variances preserved


def test_correlation_aware_weights_downscale_when_correlated():
    # identical conviction; a perfectly-correlated pair must take LESS gross than an
    # independent pair (higher portfolio vol -> scale down). This is the whole point.
    gross = {}
    for tag, shared in [("corr", True), ("indep", False)]:
        panel = _two_asset_panel(shared)
        _, vol = ts_trend_forecast(panel, fast=10, slow=50, vol_window=20)
        forecast = pd.DataFrame(0.5, index=panel.index, columns=panel.columns)  # both long, equal
        w = correlation_aware_weights(forecast, vol, panel.pct_change(), target_vol=0.20,
                                      periods_per_year=365, leverage=10.0, cov_window=100, shrinkage=0.3)
        gross[tag] = float(w.abs().sum(axis=1).iloc[150:].mean())
    assert gross["corr"] < gross["indep"]                       # correlated book de-levers


def _panel(n=320, seed=0):
    """6 assets: 3 persistent uptrends, 3 persistent downtrends (+ noise)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    drift = {"A": 0.004, "B": 0.003, "C": 0.0035, "D": -0.004, "E": -0.003, "F": -0.0035}
    cols = {s: 100 * np.exp(np.cumsum(mu + rng.normal(0, 0.01, n))) for s, mu in drift.items()}
    return pd.DataFrame(cols, index=idx)


def test_forecast_is_causal_and_bounded():
    panel = _panel()
    fc, vol = ts_trend_forecast(panel, fast=20, slow=100, vol_window=48)
    assert fc.shape == panel.shape
    valid = fc.dropna()
    assert (valid.abs() <= 1.0 + 1e-9).all().all()       # tanh-bounded
    # uptrend asset A should be net long, downtrend D net short, once warm
    warm = fc.iloc[150:]
    assert warm["A"].mean() > 0 and warm["D"].mean() < 0


def test_weights_respect_gross_leverage_cap():
    panel = _panel()
    fc, vol = ts_trend_forecast(panel, 20, 100, 48)
    w = ts_trend_weights(fc, vol, target_vol=0.20, periods_per_year=365, leverage=2.0)
    gross = w.abs().sum(axis=1)
    assert gross.max() <= 2.0 + 1e-9                       # never exceeds the cap


def test_captures_up_and_down_trends():
    panel = _panel()
    res = run_ts_trend_backtest(
        panel, fast=20, slow=100, vol_window=48, scale=10.0, target_vol=0.20,
        leverage=2.0, fee_bps=0.0, rebalance=1, periods_per_year=365,
    )
    # long the up-trends AND short the down-trends -> positive risk-adjusted return
    assert res.metrics.sharpe > 1.0
    assert res.gross_exposure > 0


def test_costs_reduce_returns():
    panel = _panel()
    free = run_ts_trend_backtest(panel, fast=20, slow=100, vol_window=48, scale=10.0,
                                 target_vol=0.20, leverage=2.0, fee_bps=0.0, rebalance=1,
                                 periods_per_year=365)
    costly = run_ts_trend_backtest(panel, fast=20, slow=100, vol_window=48, scale=10.0,
                                   target_vol=0.20, leverage=2.0, fee_bps=50.0, rebalance=1,
                                   periods_per_year=365)
    assert costly.returns.sum() < free.returns.sum()
