"""Stress / scenario replay tests (§4.8).

Two levels: (1) the standard scenarios leave a normal book SAFE; (2) when a tape is
severe enough to breach the halt threshold, the drawdown breaker actually fires and
the book de-risks — proving the safety machinery works, not just that a tiny book
survives.
"""

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from algo_trading_bot.config import BotConfig, RiskConfig, VenueConfig
from algo_trading_bot.core.events import MarketEvent
from algo_trading_bot.core.types import Bar, Symbol, VenueId
from algo_trading_bot.engine.backtest import Backtester
from algo_trading_bot.validation.stress import (
    SCENARIOS,
    flash_crash,
    run_all,
    venue_outage,
)


def _uptrend(n=260, seed=0):
    rng = np.random.default_rng(seed)
    price, t0, bars = 30000.0, datetime(2024, 1, 1, tzinfo=timezone.utc), []
    for i in range(n):
        price *= math.exp(0.0015 + rng.normal(0, 0.006))   # steady uptrend -> trend goes long
        ts = t0 + timedelta(hours=i + 1)
        bars.append(Bar(Symbol("BTC"), ts, price, price * 1.002, price * 0.998,
                        price, 100.0, VenueId("test"), knowable_at=ts))
    return bars


def _cfg(tmp_path, **risk):
    return BotConfig(
        universe=["BTC"], bar_interval="1h", data_venue="test", data_dir=str(tmp_path),
        venue=VenueConfig(name="test", max_capital_quote=0.0),
        risk=RiskConfig(**risk),
    )


def test_transforms_perturb_the_tape():
    bars = _uptrend(100)
    crashed, _ = flash_crash(bars, None, at=0.5, depth=0.3, width=3)
    assert crashed[50].close < bars[50].close * 0.8        # crash window dropped ~30%
    shorter, _ = venue_outage(bars, None, at=0.5, n_missing=10)
    assert len(shorter) == len(bars) - 10                  # outage removed bars


def test_standard_scenarios_safe(tmp_path):
    cfg = _cfg(tmp_path)
    results = run_all(cfg, _uptrend())
    assert {r.scenario for r in results} == {s.name for s in SCENARIOS}
    for r in results:
        assert r.safe, r.summary()


def test_breaker_fires_and_flattens_on_deep_crash(tmp_path):
    """Aggressive sizing + a deep sustained crash must trip the halt and de-risk."""
    cfg = _cfg(tmp_path, target_annual_vol=1.0, kelly_fraction=0.5, max_gross_leverage=1.5,
               drawdown_derisk=0.08, drawdown_halt=0.15)
    bars = _uptrend(260)
    # deep sustained crash after warmup while the trend book is long and deployed
    crashed, _ = flash_crash(bars, cfg, at=0.62, depth=0.35, width=6)

    engine = Backtester(cfg).build_engine()
    engine.run(MarketEvent(b) for b in crashed)

    eq = engine.equity_val
    peak = max(eq[: int(len(eq) * 0.62)])
    trough = min(eq[int(len(eq) * 0.62):])
    assert 1 - trough / peak >= cfg.risk.drawdown_halt      # the tape really breached the halt line
    assert engine.drawdown.halted                            # breaker fired
    assert min(eq) > 0                                       # still solvent (no blow-through)
    # after the halt, the book is forced toward flat (risk gate zeroes the target)
    assert abs(engine.portfolio.position(Symbol("BTC")).quantity) < 1e-6
