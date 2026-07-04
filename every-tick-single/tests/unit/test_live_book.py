"""
Offline smoke test for live_book — stubbed CLOB adapter, NO network.

Proves the full live bracket cycle:
    entry place → user_ws fill event → TP placed → TP fill → bar settle
plus the taker stop path, the never-cross clamp, the LIVE_MAX_ORDER_USD
notional cap, and the daily-loss kill switch.

Run:  python src/test_live_book.py            (or pytest src/test_live_book.py)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from core.btc_ws import btc_state                                    # noqa: E402
from config import (                                            # noqa: E402
    LIVE_MAX_DAILY_LOSS_USD,
    LIVE_MAX_ORDER_USD,
    TAKE_PROFIT_PRICE,
)
from engine.live_book import LiveBook                                  # noqa: E402
from core.pm_ws import pm_state                                      # noqa: E402
from engine.user_ws import user_state                                  # noqa: E402


class StubAdapter:
    """In-memory CLOB stand-in with the same 4 methods as ClobAdapter."""

    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.cancelled: list[str] = []
        self.faks: list[dict] = []
        self._seq = 0

    def place_limit(self, token_id, side, size, price):
        self._seq += 1
        eid = f"X{self._seq}"
        self.placed.append(
            {"eid": eid, "token_id": token_id, "side": side, "size": size, "price": price}
        )
        return eid

    def cancel(self, order_id):
        self.cancelled.append(order_id)
        return True

    def sell_fak(self, token_id, size, min_price):
        self._seq += 1
        eid = f"F{self._seq}"
        self.faks.append({"eid": eid, "token_id": token_id, "size": size, "min_price": min_price})
        return eid, True

    def order_status(self, order_id):
        return None


def _reset_state(now: float, cid: str = "0xcond1") -> None:
    pm_state.condition_id = cid
    pm_state.question = "BTC up or down (test)"
    pm_state.token_id_up = "TOKUP"
    pm_state.token_id_down = "TOKDOWN"
    pm_state.market_start_ts = int(now)
    pm_state.market_end_ts = int(now) + 300
    pm_state.order_min_size = 5.0
    pm_state.up_bid, pm_state.up_ask = 0.48, 0.52
    pm_state.down_bid, pm_state.down_ask = 0.46, 0.50
    btc_state.bar_open = 100000.0
    btc_state.current_price = 100100.0
    user_state.matched_shares.clear()
    user_state.avg_price.clear()
    user_state.order_status.clear()
    user_state.total_notional.clear()


def _make_book(events: list) -> tuple[LiveBook, StubAdapter]:
    book = LiveBook()
    stub = StubAdapter()
    book.set_client(stub)
    book.set_emitter(lambda et, **p: events.append((et, p)))
    return book, stub


def _fill(eid: str, size: float, price: float) -> None:
    user_state.order_status[eid] = "filled"
    user_state.matched_shares[eid] = size
    user_state.avg_price[eid] = price


async def _test_bracket_cycle() -> None:
    now = time.time()
    _reset_state(now)
    events: list = []
    book, stub = _make_book(events)

    book.observe(now)
    assert book.bar_active(), "bar should be tracked"

    # 1. Entry place (GTC BUY, maker).
    oid = book.place_quote("UP", 0.48, 10.0, now, purpose="entry")
    assert oid is not None
    assert book.resting_entry("UP") is not None
    await book.flush()
    assert stub.placed[0]["side"] == "BUY" and abs(stub.placed[0]["price"] - 0.48) < 1e-9
    placed = [p for et, p in events if et == "live_quote_placed"]
    assert placed and "bar_start_to_entry_ms" in placed[0], "entry event must carry bar_start_to_entry_ms"
    entry_eid = stub.placed[0]["eid"]

    # 2. Fill event arrives on user_ws.
    _fill(entry_eid, 10.0, 0.48)
    book.check_fills(time.time())
    await book.flush()
    assert any(et == "live_fill" for et, _ in events), "entry fill must be recorded"
    assert book.bar_entry_fills() == 1
    assert abs(book.bar_inventory("UP") - 10.0) < 1e-9

    # 3. TP placed automatically (GTC SELL at TAKE_PROFIT_PRICE, actual filled size).
    tps = [p for p in stub.placed if p["side"] == "SELL"]
    assert tps and abs(tps[0]["price"] - TAKE_PROFIT_PRICE) < 1e-9 and abs(tps[0]["size"] - 10.0) < 1e-9
    assert any(et == "live_tp_placed" for et, _ in events)
    tp_eid = tps[0]["eid"]

    # 4. TP fill.
    _fill(tp_eid, 10.0, TAKE_PROFIT_PRICE)
    book.check_fills(time.time())
    assert any(et == "live_tp_fill" for et, _ in events)
    assert abs(book.bar_inventory("UP")) < 1e-9

    # 5. Settle at expiry.
    book.observe(now + 10)  # refresh last_price while bar alive
    book.observe(pm_state.market_end_ts + 1.0)
    settles = [p for et, p in events if et == "live_bar_settle"]
    expected = 10.0 * (TAKE_PROFIT_PRICE - 0.48)
    assert settles and abs(settles[0]["bracket_pnl"] - expected) < 1e-6, settles
    assert settles[0]["positions"][0]["exit_kind"] == "tp"
    assert any(et == "live_daily_summary" for et, _ in events)
    print(f"bracket cycle OK  (entry→fill→tp→tp_fill→settle, pnl={expected:+.2f})")


async def _test_stop_path() -> None:
    now = time.time()
    _reset_state(now, cid="0xcond2")
    events: list = []
    book, stub = _make_book(events)
    book.observe(now)

    book.place_quote("UP", 0.48, 10.0, now, purpose="entry")
    await book.flush()
    _fill(stub.placed[0]["eid"], 10.0, 0.48)
    book.check_fills(time.time())
    await book.flush()
    tp_eid = [p for p in stub.placed if p["side"] == "SELL"][0]["eid"]

    # Bid collapses through the stop (config default STOP_LOSS_PRICE=0.10).
    pm_state.up_bid = 0.05
    pm_state.up_ask = 0.07
    book.check_fills(time.time())          # arms + spawns the stop task
    await asyncio.sleep(0.3)               # let the FAK go out
    assert stub.faks, "stop must fire a FAK sell"
    _fill(stub.faks[0]["eid"], 10.0, 0.05)
    await book.flush()
    assert tp_eid in stub.cancelled, "TP must be pulled before the taker stop"
    stops = [p for et, p in events if et == "live_stop_fired"]
    assert stops and stops[0]["realized_pnl"] < 0
    print(f"stop path OK  (tp cancelled, FAK sell, realized={stops[0]['realized_pnl']:+.2f})")


async def _test_guards() -> None:
    now = time.time()
    _reset_state(now, cid="0xcond3")
    events: list = []
    book, stub = _make_book(events)
    book.observe(now)

    # Never-cross clamp: BUY priced at/over the ask is clamped to ask − tick.
    pm_state.up_ask = 0.40
    book.place_quote("UP", 0.48, 5.0, now, purpose="entry")
    await book.flush()
    assert abs(stub.placed[-1]["price"] - 0.39) < 1e-9, stub.placed[-1]

    # Notional cap: 20 shares @ 0.50 = $10 > LIVE_MAX_ORDER_USD → clamped.
    pm_state.up_ask = 0.60
    book.place_quote("UP", 0.50, 20.0, now, purpose="quote")
    await book.flush()
    max_size = stub.placed[-1]["size"]
    assert max_size * 0.50 <= LIVE_MAX_ORDER_USD + 1e-9, stub.placed[-1]
    print(f"guards OK  (never-cross → 0.39, notional cap → {max_size} shares)")


async def _test_kill_switch() -> None:
    now = time.time()
    _reset_state(now, cid="0xcond4")
    events: list = []
    book, stub = _make_book(events)
    book.observe(now)

    oid = book.place_quote("UP", 0.48, 10.0, now, purpose="entry")
    assert oid is not None
    await book.flush()
    eid = stub.placed[0]["eid"]

    # Breach the daily loss limit → cancel all + halt for the UTC day.
    book._register_realized(-(LIVE_MAX_DAILY_LOSS_USD + 1.0), now)
    await book.flush()
    assert any(et == "live_kill_switch" for et, _ in events)
    assert eid in stub.cancelled, "kill switch must cancel resting orders"
    assert not book.orders
    assert book.halted(now)
    assert book.place_quote("UP", 0.48, 10.0, now, purpose="entry") is None, "halted book must refuse quotes"
    # Next UTC day the halt lifts (simulate +24h).
    assert not book.halted(now + 86400 + 60)
    print("kill switch OK  (cancel-all, quoting refused for the day, lifts next UTC day)")


async def _main() -> None:
    await _test_bracket_cycle()
    await _test_stop_path()
    await _test_guards()
    await _test_kill_switch()
    print("ALL LIVE_BOOK SMOKE TESTS PASSED")


def test_live_book_smoke() -> None:  # pytest entry point
    asyncio.run(_main())


if __name__ == "__main__":
    asyncio.run(_main())
