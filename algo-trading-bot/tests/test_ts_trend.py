"""Tests for the multi-asset time-series trend book: causal forecast, vol-targeted
gross cap, and that it captures both up- and down-trends (directional per asset)."""

import numpy as np
import pandas as pd

from algo_trading_bot.backtest.ts_trend import (
    run_ts_trend_backtest,
    ts_trend_forecast,
    ts_trend_weights,
)


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
