"""Tests for the implemented metric functions (the parts of the scaffold that are real)."""

import numpy as np

from algo_trading_bot.backtest import metrics
from algo_trading_bot.validation.stats import norm_cdf


def test_sharpe_zero_for_constant_returns():
    assert metrics.sharpe(np.zeros(100)) == 0.0


def test_sharpe_zero_when_no_variance():
    assert metrics.sharpe(np.full(252, 0.001)) == 0.0  # std 0 -> guarded to 0


def test_sharpe_positive_for_positive_drift():
    noisy = np.array([0.01, -0.005, 0.012, -0.003, 0.008] * 50)
    assert metrics.sharpe(noisy, periods_per_year=252) > 0


def test_max_drawdown_simple():
    equity = np.array([100, 110, 105, 120, 90, 95])
    mdd, dur = metrics.max_drawdown(equity)
    assert mdd < 0
    assert np.isclose(mdd, 90 / 120 - 1)
    assert dur >= 1


def test_skew_sign():
    # left-skewed sample should report negative skew
    left = np.array([0.01] * 20 + [-0.5])
    assert metrics.skew(left) < 0


def test_profit_factor():
    assert metrics.profit_factor(np.array([2.0, -1.0, 1.0])) == 3.0


def test_norm_cdf_known_values():
    assert abs(norm_cdf(0.0) - 0.5) < 1e-9
    assert norm_cdf(10) > 0.999999
