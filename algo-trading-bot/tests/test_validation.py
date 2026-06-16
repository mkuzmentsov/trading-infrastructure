"""Tests for the OOS validation harness: inverse-normal, DSR, the gate, and the
end-to-end in-sample-tune -> out-of-sample-test flow on synthetic data."""

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from algo_trading_bot.config import BotConfig, VenueConfig
from algo_trading_bot.core.types import Bar, Symbol, VenueId
from algo_trading_bot.validation.baseline_oos import run_oos_validation
from algo_trading_bot.validation.deflated_sharpe import _inv_norm_cdf
from algo_trading_bot.validation.gate import ApproveForLiveGate
from algo_trading_bot.validation.stats import norm_cdf
from algo_trading_bot.config import ValidationConfig
from algo_trading_bot.engine.backtest import Backtester


def test_inv_norm_cdf_roundtrip():
    assert math.isclose(_inv_norm_cdf(0.975), 1.959964, abs_tol=1e-4)
    for p in (0.01, 0.2, 0.5, 0.8, 0.99):
        assert abs(norm_cdf(_inv_norm_cdf(p)) - p) < 1e-6


def test_gate_rejects_negative_sharpe():
    gate = ApproveForLiveGate(ValidationConfig())
    res = gate.evaluate({"oos_sharpe": -0.5, "deflated_sharpe": 0.1})
    assert not res.approved
    assert any(c.name == "positive_oos_sharpe" and not c.passed for c in res.checks)


def test_gate_partial_evidence_only_adds_present_checks():
    gate = ApproveForLiveGate(ValidationConfig())
    res = gate.evaluate({"oos_sharpe": 1.0, "deflated_sharpe": 0.99})
    names = {c.name for c in res.checks}
    assert "pbo" not in names          # no PBO evidence -> no PBO check
    assert res.approved                 # positive Sharpe + significant DSR -> pass


def test_gate_empty_evidence_not_approved():
    assert not ApproveForLiveGate(ValidationConfig()).evaluate({}).approved


def _write_trending_bars(store, n=900, seed=1):
    rng = np.random.default_rng(seed)
    price = 30000.0
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        price *= math.exp(0.0006 + rng.normal(0, 0.012))
        ts = t0 + timedelta(hours=i + 1)
        bars.append(Bar(Symbol("BTC"), ts, price, price * 1.002, price * 0.998,
                        price, 100.0, VenueId("test"), knowable_at=ts))
    store.append_bars(bars)


def test_oos_validation_runs_and_splits(tmp_path):
    cfg = BotConfig(
        universe=["BTC"], bar_interval="1h", data_venue="test", data_dir=str(tmp_path),
        venue=VenueConfig(name="test", max_capital_quote=0.0),
    )
    bt = Backtester(cfg)
    _write_trending_bars(bt.store, n=900)

    r = run_oos_validation(cfg, datetime(2024, 1, 1, tzinfo=timezone.utc),
                           datetime(2024, 3, 1, tzinfo=timezone.utc), train_frac=0.6)
    assert r.n_trials == len(r.trials) > 1
    assert "ema_fast" in r.best_params and "ema_slow" in r.best_params
    assert r.test_bars > 0
    assert 0.0 <= r.deflated_sharpe <= 1.0
    assert np.isfinite(r.oos_metrics.sharpe)
