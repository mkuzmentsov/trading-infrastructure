"""End-to-end test of the first vertical slice on synthetic data (no network).

Writes a deterministic trending price series into the store, runs the full engine
(features -> trend -> combine -> size -> risk -> oms -> fills), and asserts the
backtest produces a sane equity curve and takes trades. Also unit-tests the
portfolio accounting and the vol-target sizer.
"""

import math
from datetime import datetime, timedelta, timezone

import numpy as np

from algo_trading_bot.backtest.friction import FillSimulator
from algo_trading_bot.config import BotConfig, FrictionConfig, RiskConfig, VenueConfig
from algo_trading_bot.core.types import Fill, Side, Symbol, TargetPosition, VenueId
from algo_trading_bot.engine.backtest import Backtester
from algo_trading_bot.engine.portfolio import Portfolio


def _make_bars(store, n=600, seed=0):
    """A gently trending + noisy 1h BTC series, written as canonical bars."""
    from algo_trading_bot.core.types import Bar

    rng = np.random.default_rng(seed)
    price = 30000.0
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        # upward drift with mean-reverting noise -> a real trend the baseline can ride
        price *= math.exp(0.0008 + rng.normal(0, 0.01))
        ts = t0 + timedelta(hours=i + 1)
        bars.append(Bar(Symbol("BTC"), ts, price, price * 1.002, price * 0.998,
                        price, 100.0, VenueId("test"), knowable_at=ts))
    store.append_bars(bars)


def _config(tmp_path):
    return BotConfig(
        name="t", universe=["BTC"], bar_interval="1h", starting_cash=10_000.0,
        venue=VenueConfig(name="test", testnet=True, max_capital_quote=0.0),
        friction=FrictionConfig(), risk=RiskConfig(),
        data_dir=str(tmp_path),
    )


def test_backtest_runs_end_to_end(tmp_path):
    bt = Backtester(_config(tmp_path))
    _make_bars(bt.store, n=600)
    res = bt.run(datetime(2024, 1, 1, tzinfo=timezone.utc),
                 datetime(2024, 4, 1, tzinfo=timezone.utc), venue="test")

    assert len(res.equity) > 400              # most bars produced an equity point
    assert len(res.trades) > 0                # the strategy actually traded
    assert res.equity.iloc[0] > 0
    assert np.isfinite(res.metrics.sharpe)
    assert res.provenance.data_snapshot_id    # provenance stamped (§3.4)
    # On a persistent uptrend the long-biased trend baseline should not be ruined.
    assert res.equity.iloc[-1] > res.equity.iloc[0] * 0.5


def test_portfolio_long_then_close_realizes_pnl():
    pf = Portfolio(10_000.0)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    pf.apply_fill(Fill("o1", Symbol("BTC"), Side.LONG, 1.0, 100.0, 0.0, ts))
    assert pf.position(Symbol("BTC")).quantity == 1.0
    assert pf.position(Symbol("BTC")).avg_price == 100.0
    realized = pf.apply_fill(Fill("o2", Symbol("BTC"), Side.SHORT, 1.0, 110.0, 0.0, ts))
    assert math.isclose(realized, 10.0)       # +$10 on a 1-unit long from 100 -> 110
    assert pf.position(Symbol("BTC")).quantity == 0.0
    assert math.isclose(pf.cash, 10_010.0)    # back to flat, +$10 cash


def test_sizer_shrinks_with_higher_vol():
    from algo_trading_bot.arbitration.sizing import VolTargetSizer

    risk = RiskConfig()
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sizer = VolTargetSizer(risk, capital_quote=10_000.0, periods_per_year=365 * 24)
    lo = sizer.size(Symbol("BTC"), 1.0, realized_vol=0.005, ts=ts)
    hi = sizer.size(Symbol("BTC"), 1.0, realized_vol=0.02, ts=ts)
    assert abs(hi.notional) < abs(lo.notional)             # more vol -> smaller position
    assert abs(lo.notional) <= 10_000.0 * risk.max_gross_leverage + 1e-6  # leverage cap


def test_fill_simulator_applies_fee_and_slippage():
    sim = FillSimulator(FrictionConfig(taker_fee_bps=10.0))
    sim.update_market(Symbol("BTC"), 100.0)
    from algo_trading_bot.core.types import Order, OrderType

    sim.place(Order("c1", Symbol("BTC"), Side.LONG, 1.0, OrderType.MARKET))
    fills = sim.poll_fills()
    assert len(fills) == 1
    assert fills[0].price > 100.0     # buyer pays up (slippage)
    assert fills[0].fee > 0
