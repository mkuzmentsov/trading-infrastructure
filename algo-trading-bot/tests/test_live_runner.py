"""Tests for the paper runner: audit log, persistence + safe restart (NFR4), and the
real-money live guard."""

import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from algo_trading_bot.config import BotConfig, VenueConfig
from algo_trading_bot.core.types import Bar, Symbol, VenueId
from algo_trading_bot.engine.backtest import Backtester
from algo_trading_bot.engine.live import LiveRunner
from algo_trading_bot.monitoring.audit_log import AuditLog


def test_audit_log_roundtrip(tmp_path):
    log = AuditLog(tmp_path / "d.jsonl")
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    log.decision("bar", ts, {"nav": 100.0})
    log.decision("bar", ts, {"nav": 101.0})
    rows = list(log.replay())
    assert [r["nav"] for r in rows] == [100.0, 101.0]
    assert all(r["kind"] == "bar" for r in rows)


def _seed_store(cfg, n=300, seed=0):
    rng = np.random.default_rng(seed)
    price, t0, bars = 30000.0, datetime(2024, 1, 1, tzinfo=timezone.utc), []
    for i in range(n):
        price *= math.exp(0.001 + rng.normal(0, 0.01))
        ts = t0 + timedelta(hours=i + 1)
        bars.append(Bar(Symbol("BTC"), ts, price, price * 1.002, price * 0.998,
                        price, 100.0, VenueId("test"), knowable_at=ts))
    Backtester(cfg).store.append_bars(bars, "1h")


def _cfg(tmp_path):
    return BotConfig(
        name="papertest", universe=["BTC"], bar_interval="1h", data_venue="test",
        data_dir=str(tmp_path / "data"),
        venue=VenueConfig(name="test", max_capital_quote=0.0),
    )


def test_paper_run_persists_and_restarts(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_store(cfg, n=300)
    state_dir = str(tmp_path / "state")

    LiveRunner(cfg, mode="paper", source="replay", speed=0, max_bars=200,
               state_dir=state_dir).run()

    st = json.loads((tmp_path / "state" / "papertest_state.json").read_text())
    assert st["bars_processed"] == 200
    assert "BTC" in st["positions"]
    cash_after_first = st["cash"]

    # Restart: a fresh runner restores cash + position rather than starting clean (NFR4).
    runner2 = LiveRunner(cfg, mode="paper", source="replay", speed=0, max_bars=1,
                         state_dir=state_dir)
    engine = Backtester(cfg).build_engine()
    restored = runner2._restore(engine)
    assert restored == 200
    assert engine.portfolio.cash == cash_after_first
    assert engine.portfolio.position(Symbol("BTC")).quantity == st["positions"]["BTC"]["quantity"]


def test_live_mode_is_guarded(tmp_path):
    cfg = _cfg(tmp_path)
    _seed_store(cfg, n=120)
    runner = LiveRunner(cfg, mode="live", source="replay", speed=0, max_bars=10,
                        state_dir=str(tmp_path / "state"))
    with pytest.raises(SystemExit, match="REFUSING live"):
        runner.run()
