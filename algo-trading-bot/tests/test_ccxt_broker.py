"""Tests for the live CcxtBroker order/fill/position mapping — with a MOCK exchange.

No network, no real orders, no credentials. Asserts Order/Fill/Position translate to
and from ccxt's unified shapes correctly, and that fills de-dup across polls.
"""

from algo_trading_bot.core.types import Order, OrderType, Side, Symbol
from algo_trading_bot.execution.ccxt_broker import CcxtBroker


class FakeExchange:
    """Minimal ccxt-shaped stand-in capturing calls and returning canned responses."""

    def __init__(self):
        self.has = {"fetchPositions": True, "fetchMyTrades": True}
        self.created = []
        self.canceled = []
        self._trades = []
        self._positions = []
        self._balance = {}
        self._now_ms = 1_000_000

    def milliseconds(self):
        return self._now_ms

    def fetch_balance(self):
        return self._balance

    def create_order(self, symbol, otype, side, amount, price=None, params=None):
        self.created.append({"symbol": symbol, "type": otype, "side": side,
                             "amount": amount, "price": price, "params": params})
        return {"id": f"oid-{len(self.created)}", "clientOrderId": (params or {}).get("clientOrderId")}

    def cancel_order(self, oid):
        self.canceled.append(oid)

    def fetch_open_orders(self):
        return []

    def fetch_positions(self):
        return self._positions

    def fetch_my_trades(self, since=None):
        # ccxt semantics: only trades at/after `since`
        return [t for t in self._trades if since is None or t["timestamp"] >= since]


def _broker():
    return CcxtBroker("kraken", client=FakeExchange())


def test_equity_reads_real_balance():
    b = _broker()
    b.client._balance = {"total": {"USD": 81.37}}
    assert b.equity() == 81.37
    # flex/multi-collateral account: portfolioValue in info
    b.client._balance = {"info": {"accounts": {"flex": {"portfolioValue": "123.5"}}}, "total": {}}
    assert b.equity() == 123.5
    # unavailable -> 0.0 (caller keeps prior capital)
    b.client._balance = {"total": {}}
    assert b.equity() == 0.0


def test_restart_cursor_skips_pre_restart_fills():
    # a trade exists from BEFORE restart; the engine reconciles position from the venue, so this
    # fill must NOT be replayed. seen_through_now() advances the cursor past it.
    b = _broker()
    b.client._now_ms = 5_000
    b.client._trades = [{"id": "t1", "timestamp": 4_000, "order": "o1", "symbol": "BTC/USD",
                         "side": "buy", "amount": 0.1, "price": 100.0, "fee": {"cost": 0.05}}]
    b.seen_through_now()                       # restart: cursor -> 5_000
    assert b.poll_fills() == []               # the old (t=4_000) trade is skipped
    # a NEW post-restart fill IS applied
    b.client._trades.append({"id": "t2", "timestamp": 6_000, "order": "o2", "symbol": "BTC/USD",
                             "side": "sell", "amount": 0.1, "price": 101.0, "fee": {"cost": 0.05}})
    fills = b.poll_fills()
    assert len(fills) == 1 and fills[0].order_id == "o2"


def test_place_maps_side_and_clientid():
    b = _broker()
    b.place(Order("cid-1", Symbol("BTC"), Side.LONG, 0.5, OrderType.MARKET))
    call = b.client.created[0]
    assert call["symbol"] == "BTC/USD"          # canonical -> venue market
    assert call["side"] == "buy"                 # LONG -> buy
    assert call["amount"] == 0.5
    assert call["params"]["clientOrderId"] == "cid-1"
    assert b._order_ids["cid-1"] == "oid-1"      # tracked for cancel

    b.place(Order("cid-2", Symbol("BTC"), Side.SHORT, 1.0, OrderType.MARKET))
    assert b.client.created[1]["side"] == "sell"  # SHORT -> sell


def test_cancel_uses_venue_order_id():
    b = _broker()
    b.place(Order("cid-1", Symbol("BTC"), Side.LONG, 0.5, OrderType.MARKET))
    b.cancel("cid-1")
    assert b.client.canceled == ["oid-1"]        # mapped client_id -> venue id


def test_poll_fills_maps_and_dedups():
    b = _broker()
    b.client._trades = [
        {"id": "t1", "order": "oid-1", "symbol": "BTC/USD", "side": "buy",
         "amount": 0.5, "price": 50000.0, "fee": {"cost": 1.25}, "timestamp": 1700000000000,
         "takerOrMaker": "taker"},
    ]
    fills = b.poll_fills()
    assert len(fills) == 1
    f = fills[0]
    assert f.symbol == Symbol("BTC") and f.side == Side.LONG
    assert f.quantity == 0.5 and f.price == 50000.0 and f.fee == 1.25
    # polling again returns nothing for the same trade id (dedup)
    assert b.poll_fills() == []


def test_krakenfutures_uses_perp_market_symbol():
    b = CcxtBroker("krakenfutures", client=FakeExchange())
    b.place(Order("cid-1", Symbol("BTC"), Side.SHORT, 0.5, OrderType.MARKET))
    assert b.client.created[0]["symbol"] == "BTC/USD:USD"   # USD-settled perpetual
    assert b.client.created[0]["side"] == "sell"            # short is valid on perps


def test_positions_signed_for_perps():
    b = CcxtBroker("hyperliquid", client=FakeExchange())
    b.client._positions = [
        {"symbol": "ETH/USDC:USDC", "contracts": 2.0, "side": "short", "entryPrice": 3000.0},
    ]
    pos = b.positions()
    assert pos[Symbol("ETH")].quantity == -2.0   # short -> negative
    assert pos[Symbol("ETH")].avg_price == 3000.0


def test_spot_venue_returns_no_positions():
    b = _broker()
    b.client.has["fetchPositions"] = False
    assert b.positions() == {}
