"""Real venue order I/O via ccxt — the live ExecutionAdapter (§2.6, §8).

One generic broker drives any ccxt venue (Kraken spot, Hyperliquid perps, ...); the
per-venue adapters (adapters/) are thin credential wrappers around it. The OMS and the
whole decision path are identical to the backtest (NFR1) — only this output side and
the data source change.

Safety: this places REAL orders. It is reached only through the guarded `live` mode
(engine/live.py refuses without a recorded gate pass). The ccxt client is injectable
so tests exercise the mapping with a mock — never a live account.

Mapping choices:
* Order.side LONG/SHORT encodes trade direction (the OMS sets it from the current→target
  gap), so LONG→"buy", SHORT→"sell".
* client_id is passed as the venue clientOrderId for idempotency/dedup (§2.6, §7.3).
* poll_fills pulls fetch_my_trades since the last seen trade and de-dups by trade id.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..core.types import Fill, Order, OrderType, Position, Side, Symbol, VenueId
from ..data.bars import normalize_symbol
from ..data.fetch import _market_symbol


class CcxtBroker:
    """ExecutionAdapter backed by a ccxt exchange client."""

    def __init__(self, venue: str, *, ccxt_config: dict | None = None, client=None) -> None:
        self.venue = venue
        if client is not None:
            self.client = client            # injected (tests / custom)
        else:
            import ccxt

            self.client = getattr(ccxt, venue)(ccxt_config or {})
        # client_id -> venue order id, for cancels
        self._order_ids: dict[str, str] = {}
        self._seen_trades: set[str] = set()
        self._last_trade_ms: int = 0

    def _market(self, symbol: Symbol) -> str:
        return _market_symbol(self.venue, str(symbol))

    # --- order I/O ---
    def place(self, order: Order) -> None:
        side = "buy" if order.side == Side.LONG else "sell"
        otype = "market" if order.order_type == OrderType.MARKET else "limit"
        params = {"clientOrderId": order.client_id}
        resp = self.client.create_order(
            self._market(order.symbol), otype, side, order.quantity,
            order.limit_price, params,
        )
        if isinstance(resp, dict) and resp.get("id"):
            self._order_ids[order.client_id] = resp["id"]

    def cancel(self, client_id: str) -> None:
        oid = self._order_ids.get(client_id, client_id)
        self.client.cancel_order(oid)

    def open_orders(self) -> list[Order]:
        out: list[Order] = []
        for o in self.client.fetch_open_orders():
            out.append(
                Order(
                    client_id=o.get("clientOrderId") or o.get("id", ""),
                    symbol=normalize_symbol(o.get("symbol", ""), self.venue),
                    side=Side.LONG if o.get("side") == "buy" else Side.SHORT,
                    quantity=float(o.get("amount") or 0.0),
                    order_type=OrderType.LIMIT if o.get("type") == "limit" else OrderType.MARKET,
                    limit_price=o.get("price"),
                    venue=VenueId(self.venue),
                    filled_quantity=float(o.get("filled") or 0.0),
                )
            )
        return out

    def positions(self) -> dict[Symbol, Position]:
        """Net positions where the venue supports it (perps). Spot venues return {}."""
        if not getattr(self.client, "has", {}).get("fetchPositions"):
            return {}
        out: dict[Symbol, Position] = {}
        for p in self.client.fetch_positions():
            contracts = float(p.get("contracts") or 0.0)
            if contracts == 0:
                continue
            signed = contracts if p.get("side") == "long" else -contracts
            sym = normalize_symbol(p.get("symbol", ""), self.venue)
            out[sym] = Position(symbol=sym, quantity=signed,
                                avg_price=float(p.get("entryPrice") or 0.0))
        return out

    def poll_fills(self) -> list[Fill]:
        if not getattr(self.client, "has", {}).get("fetchMyTrades", True):
            return []
        since = self._last_trade_ms or None
        trades = self.client.fetch_my_trades(since=since)
        fills: list[Fill] = []
        for t in trades:
            tid = str(t.get("id"))
            if tid in self._seen_trades:
                continue
            self._seen_trades.add(tid)
            ts_ms = int(t.get("timestamp") or 0)
            self._last_trade_ms = max(self._last_trade_ms, ts_ms)
            fee = (t.get("fee") or {}).get("cost") or 0.0
            fills.append(
                Fill(
                    order_id=t.get("order") or t.get("id", ""),
                    symbol=normalize_symbol(t.get("symbol", ""), self.venue),
                    side=Side.LONG if t.get("side") == "buy" else Side.SHORT,
                    quantity=float(t.get("amount") or 0.0),
                    price=float(t.get("price") or 0.0),
                    fee=float(fee),
                    ts=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else datetime.now(timezone.utc),
                    venue=VenueId(self.venue),
                    is_maker=(t.get("takerOrMaker") == "maker"),
                )
            )
        return fills
