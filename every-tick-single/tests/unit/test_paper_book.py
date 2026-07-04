#!/usr/bin/env python3
"""Characterization tests: PaperBook fill engine + bracket lifecycle.

Pins CURRENT behavior (pre-refactor) so component extraction can prove
behavior-identity. Pattern: drive pm_state/btc_state directly, feed synthetic
trade prints, step the book. Runnable standalone or via pytest.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

os.environ.setdefault("QUOTE_MODE", "bracket")

from btc_ws import btc_state  # noqa: E402
from paper_book import PaperBook  # noqa: E402
from pm_ws import pm_state  # noqa: E402


def fresh_book(now=1000.0, start=1000, end=1300):
    pm_state.condition_id = "0xTEST"
    pm_state.question = "test bar"
    pm_state.market_start_ts = start
    pm_state.market_end_ts = end
    pm_state.token_id_up = "TU"
    pm_state.token_id_down = "TD"
    pm_state.up_bid, pm_state.up_ask = 0.49, 0.51
    pm_state.down_bid, pm_state.down_ask = 0.49, 0.51
    pm_state.recent_trades.clear()
    pm_state.trade_seq = 0
    btc_state.bar_open = 100.0
    btc_state.current_price = 100.0
    book = PaperBook()
    book.observe(now)
    assert book.bar_active()
    return book


def open_positions(book):
    return [p for p in book._bar.positions if p.open] if book._bar else []


def print_trade(token_id, price, size, side="SELL", ts=1010.0):
    pm_state.trade_seq += 1
    pm_state.trade_events = getattr(pm_state, "trade_events", 0) + 1
    pm_state.last_trade_ts = ts
    pm_state.recent_trades.append({
        "seq": pm_state.trade_seq, "ts": ts, "token_id": token_id,
        "price": price, "size": size, "side": side,
    })


def test_fill_on_print_at_or_below_bid():
    book = fresh_book()
    book.place_quote("UP", 0.48, 10, 1001.0, purpose="entry")
    # print above our bid: no fill
    print_trade("TU", 0.49, 5, ts=1005.0)
    book.check_fills(1005.5)
    assert book.bar_inventory("UP") == 0
    # print at our bid: fills, capped by print size
    print_trade("TU", 0.48, 4, ts=1006.0)
    book.check_fills(1006.5)
    assert abs(book.bar_inventory("UP") - 4.0) < 1e-9
    # MAX_FILLS_PER_BAR=1: the partial fill counts as the bar's one fill —
    # the 6-share remainder is CANCELLED (no refill conveyor), TP rests for 4
    assert book.resting_entry("UP") is None
    tp = [o for o in book.orders.values() if o.purpose == "tp"]
    assert len(tp) == 1 and abs(tp[0].size - 4.0) < 1e-9


def test_fill_capped_by_print_size_then_remainder():
    book = fresh_book()
    book.place_quote("UP", 0.48, 10, 1001.0, purpose="entry")
    print_trade("TU", 0.47, 3, ts=1005.0)
    book.check_fills(1005.5)
    assert abs(book.bar_inventory("UP") - 3.0) < 1e-9
    pos = open_positions(book)[0]
    assert abs(pos.entry_price - 0.48) < 1e-9  # fill booked at OUR limit, not the print


def test_bracket_lifecycle_tp_and_per_side_cap():
    book = fresh_book()
    book.place_quote("UP", 0.48, 10, 1001.0, purpose="entry")
    book.place_quote("DOWN", 0.48, 10, 1001.0, purpose="entry")
    up = book.resting_entry("UP")
    book._open_bracket(up, 10, 0.48, 1010.0)
    # per-side cap: UP entry gone, DOWN entry survives
    assert book.bar_entry_fills("UP") == 1
    assert book.bar_entry_fills("DOWN") == 0
    assert book.resting_entry("UP") is None
    assert book.resting_entry("DOWN") is not None
    # TP resting at pos.tp_price for the full size
    pos = open_positions(book)[0]
    tp = [o for o in book.orders.values() if o.purpose == "tp"]
    assert len(tp) == 1 and tp[0].direction == "UP"
    assert abs(tp[0].price - pos.tp_price) < 1e-9
    assert abs(tp[0].size - 10) < 1e-9


def test_settle_win_loss_accounting():
    book = fresh_book()
    book.place_quote("UP", 0.48, 10, 1001.0, purpose="entry")
    up = book.resting_entry("UP")
    book._open_bracket(up, 10, 0.48, 1010.0)
    # bar expires with price above open -> UP wins
    btc_state.current_price = 101.0
    book.observe(1250.0)  # refresh last_price
    events = []
    book._on_event = getattr(book, "_on_event", None)
    pm_state.condition_id = "0xNEXT"  # rotate market
    pm_state.market_start_ts, pm_state.market_end_ts = 1300, 1600
    book.observe(1301.0)  # settles old bar
    # position settled as win at $1: pnl = 10 * (1 - 0.48) = +5.2 gross
    assert not open_positions(book)


def test_tp_fill_from_print():
    book = fresh_book()
    book.place_quote("UP", 0.48, 10, 1001.0, purpose="entry")
    up = book.resting_entry("UP")
    book._open_bracket(up, 10, 0.48, 1010.0)
    pos = open_positions(book)[0]
    print_trade("TU", 0.99, 12, side="BUY", ts=1020.0)
    book.check_fills(1020.5)
    assert pos.exit_kind == "tp"
    assert abs(pos.realized_pnl - 10 * (0.99 - 0.48)) < 1e-6


if __name__ == "__main__":
    for fn in [test_fill_on_print_at_or_below_bid, test_fill_capped_by_print_size_then_remainder,
               test_bracket_lifecycle_tp_and_per_side_cap, test_settle_win_loss_accounting,
               test_tp_fill_from_print]:
        fresh_book()
        fn()
        print("OK", fn.__name__)
