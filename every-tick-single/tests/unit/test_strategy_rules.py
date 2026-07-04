#!/usr/bin/env python3
"""Characterization tests: maker_rebate strategy rules — alternate side flip,
p_up bar metadata, startup gate, bar_snapshot cadence."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

os.environ.setdefault("QUOTE_MODE", "bracket")
os.environ.setdefault("BRACKET_SIDES", "one")
os.environ.setdefault("BRACKET_SIDE_RULE", "alternate")
os.environ.setdefault("PAPER_MODE", "true")

from core.btc_ws import btc_state  # noqa: E402
from engine.paper_book import PaperBook  # noqa: E402
from core.pm_ws import pm_state  # noqa: E402
import strategy.maker_rebate as mr  # noqa: E402


class Ctx:
    seconds_left = 290
    up_bid, up_ask = 0.49, 0.51
    down_bid, down_ask = 0.49, 0.51
    current_price = 100.0
    binance_price = 100.0
    bar_open = 100.0
    sigma_5m = 0.001
    ret_60s = 0.0
    ml_p_up = None


def make(start=1000, cid="0xA"):
    pm_state.condition_id = cid
    pm_state.question = "t"
    pm_state.market_start_ts = start
    pm_state.market_end_ts = start + 300
    pm_state.token_id_up = "TU"
    pm_state.token_id_down = "TD"
    pm_state.up_bid, pm_state.up_ask = 0.49, 0.51
    pm_state.down_bid, pm_state.down_ask = 0.49, 0.51
    pm_state.recent_trades.clear()
    btc_state.bar_open = 100.0
    btc_state.current_price = 100.0
    strat = mr.MakerRebateStrategy()
    strat._startup_checked = True  # bypass startup gate unless testing it
    book = PaperBook()
    book.observe(float(start) + 1)
    return strat, book


def test_alternate_flips_each_bar():
    strat, book = make(1000, "0xA")
    ctx = Ctx()
    strat._maintain_bracket(ctx, book, 1001.0)
    first = book.resting_entry("UP") or book.resting_entry("DOWN")
    side1 = first.direction
    # rotate to next bar
    pm_state.condition_id = "0xB"
    pm_state.market_start_ts, pm_state.market_end_ts = 1300, 1600
    book.observe(1301.0)
    strat._maintain_bracket(ctx, book, 1301.0)
    second = book.resting_entry("UP") or book.resting_entry("DOWN")
    assert second.direction != side1, "alternate rule must flip sides per bar"
    assert side1 == "UP", "alternate starts with UP"


def test_bar_meta_recorded():
    strat, book = make(1000, "0xM")
    strat._maintain_bracket(Ctx(), book, 1001.0)
    assert book._bar.side_rule == "alternate"
    assert book._bar.p_up is not None


def test_startup_gate_skips_midbar():
    strat, book = make(1000, "0xG")
    strat._startup_checked = False
    ctx = Ctx()
    ctx.seconds_left = 150  # elapsed 150s > 10 → skip this bar
    strat._maintain_bracket(ctx, book, 1150.0)
    assert book.resting_entry("UP") is None and book.resting_entry("DOWN") is None
    # next bar trades normally
    pm_state.condition_id = "0xH"
    pm_state.market_start_ts, pm_state.market_end_ts = 1300, 1600
    book.observe(1301.0)
    ctx.seconds_left = 289  # past the 10s paper warmup
    strat._maintain_bracket(ctx, book, 1311.0)
    assert (book.resting_entry("UP") or book.resting_entry("DOWN")) is not None


def test_startup_gate_allows_fresh_bar():
    strat, book = make(1000, "0xF")
    strat._startup_checked = False
    ctx = Ctx()
    # first eligible tick is at elapsed==10 (paper warmup); gate allows <=10
    ctx.seconds_left = 290
    strat._maintain_bracket(ctx, book, 1010.0)
    assert (book.resting_entry("UP") or book.resting_entry("DOWN")) is not None


def test_snapshot_cadence():
    strat, book = make(1000, "0xS")
    events = []
    book._event = lambda et, **kw: events.append(et)
    strat._last_snapshot = 0.0
    strat._maybe_snapshot(Ctx(), book, 1000.0)
    strat._maybe_snapshot(Ctx(), book, 1005.0)   # < BAR_SNAPSHOT_SECS(15) later
    strat._maybe_snapshot(Ctx(), book, 1016.0)   # >= 15s later
    assert events.count("bar_snapshot") == 2


if __name__ == "__main__":
    for fn in [test_alternate_flips_each_bar, test_bar_meta_recorded,
               test_startup_gate_skips_midbar, test_startup_gate_allows_fresh_bar,
               test_snapshot_cadence]:
        fn()
        print("OK", fn.__name__)
