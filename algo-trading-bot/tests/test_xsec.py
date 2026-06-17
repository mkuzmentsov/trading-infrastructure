"""Tests for the cross-sectional momentum panel: dollar-neutrality, lookahead
alignment, and that it captures a rigged momentum effect."""

import numpy as np
import pandas as pd

from algo_trading_bot.backtest import metrics as M
from algo_trading_bot.backtest.panel import (
    cross_sectional_weights,
    momentum_signal,
    run_panel_backtest,
)


def _panel(n=240, seed=0):
    """5 assets: A trends up, B trends down, C/D/E drift noisily."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    drift = {"A": 0.004, "B": -0.004, "C": 0.0005, "D": -0.0005, "E": 0.0}
    cols = {}
    for sym, mu in drift.items():
        rets = mu + rng.normal(0, 0.01, n)
        cols[sym] = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(cols, index=idx)


def test_weights_are_dollar_neutral():
    panel = _panel()
    sig = momentum_signal(panel, lookback=30)
    w = cross_sectional_weights(sig, top_frac=0.2, rebalance=7, leverage=1.0)
    row = w.dropna().iloc[-1]
    assert abs(row.sum()) < 1e-9                       # long notional == short notional
    assert abs(row.abs().sum() - 1.0) < 1e-9           # gross exposure == leverage


def test_signal_is_causal():
    panel = _panel()
    sig = momentum_signal(panel, lookback=30, skip=0)
    # signal at row i must equal close[i]/close[i-30]-1 — uses only past/current
    i = 100
    expected = panel.iloc[i] / panel.iloc[i - 30] - 1.0
    pd.testing.assert_series_equal(sig.iloc[i], expected, check_names=False)


def test_captures_rigged_momentum():
    panel = _panel()
    res = run_panel_backtest(
        panel, lookback=30, skip=0, top_frac=0.2, rebalance=7, leverage=1.0,
        fee_bps=0.0, periods_per_year=365,
    )
    # long the persistent winner, short the persistent loser -> positive Sharpe
    assert res.metrics.sharpe > 1.0
    assert res.gross_exposure > 0


def test_costs_reduce_returns():
    panel = _panel()
    free = run_panel_backtest(panel, lookback=30, skip=0, top_frac=0.2, rebalance=7,
                              leverage=1.0, fee_bps=0.0, periods_per_year=365)
    costly = run_panel_backtest(panel, lookback=30, skip=0, top_frac=0.2, rebalance=7,
                                leverage=1.0, fee_bps=50.0, periods_per_year=365)
    assert costly.returns.sum() < free.returns.sum()   # turnover costs bite
