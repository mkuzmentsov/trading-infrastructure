"""Shared per-symbol market state, fed by venue feeds and read by the WS server.

One `SymbolState` per symbol holds each venue's latest quote/trade plus a short
rolling trade log for volume windows. `snapshot()` produces the normalized tick
that gets broadcast to clients. With a single venue the aggregate price is just
that venue's price; the median/offset logic activates once >=3 venues run.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass, field


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class VenueQuote:
    price: float | None = None          # last trade price
    bid: float | None = None
    ask: float | None = None
    bid_sz: float | None = None
    ask_sz: float | None = None
    last_qty: float | None = None
    last_side: str | None = None        # "buy" | "sell" (aggressor)
    bids: list | None = None            # depth ladder [[px, sz], ...] best-first
    asks: list | None = None
    ts_ms: int = 0                       # last update (any field) epoch ms


@dataclass
class SymbolState:
    symbol: str
    depth_levels: int = 10               # ladder depth exposed in snapshots
    venues: dict[str, VenueQuote] = field(default_factory=dict)
    # rolling trade log: (ts_ms, base_qty) for volume windows
    _trades: deque = field(default_factory=lambda: deque(maxlen=20000))

    def _vq(self, venue: str) -> VenueQuote:
        vq = self.venues.get(venue)
        if vq is None:
            vq = VenueQuote()
            self.venues[venue] = vq
        return vq

    def on_trade(self, venue: str, price: float, qty: float, side: str) -> None:
        vq = self._vq(venue)
        vq.price = price
        vq.last_qty = qty
        vq.last_side = side
        vq.ts_ms = now_ms()
        self._trades.append((vq.ts_ms, qty))

    def on_book(self, venue: str, bid: float, bid_sz: float, ask: float, ask_sz: float) -> None:
        vq = self._vq(venue)
        vq.bid, vq.bid_sz, vq.ask, vq.ask_sz = bid, bid_sz, ask, ask_sz
        vq.ts_ms = now_ms()

    def on_depth(self, venue: str, bids: list, asks: list) -> None:
        """Full depth ladder. bids best-first (desc px), asks best-first (asc px),
        each entry [px, sz]. Also refreshes the top-of-book from level 0."""
        vq = self._vq(venue)
        vq.bids, vq.asks = bids, asks
        if bids:
            vq.bid, vq.bid_sz = bids[0][0], bids[0][1]
        if asks:
            vq.ask, vq.ask_sz = asks[0][0], asks[0][1]
        vq.ts_ms = now_ms()

    def _fresh_prices(self, max_age_ms: int = 10_000) -> list[float]:
        t = now_ms()
        return [vq.price for vq in self.venues.values()
                if vq.price and t - vq.ts_ms < max_age_ms]

    def aggregate_price(self) -> float | None:
        px = self._fresh_prices()
        if not px:
            return None
        # median filters single-venue noise; with 1 venue it IS that price.
        return statistics.median(px)

    def volume(self, window_ms: int) -> float:
        cutoff = now_ms() - window_ms
        return sum(q for ts, q in self._trades if ts >= cutoff)

    def snapshot(self) -> dict | None:
        agg = self.aggregate_price()
        if agg is None:
            return None
        t = now_ms()
        # primary book = the freshest venue that has a two-sided quote
        book_v = None
        for v, vq in self.venues.items():
            if vq.bid and vq.ask and (book_v is None or vq.ts_ms > self.venues[book_v].ts_ms):
                book_v = v
        b = self.venues.get(book_v) if book_v else None
        n = self.depth_levels
        return {
            "type": "tick",
            "symbol": self.symbol,
            "ts": t,
            "price": round(agg, 4),
            "bid": b.bid if b else None,
            "ask": b.ask if b else None,
            "bid_sz": b.bid_sz if b else None,
            "ask_sz": b.ask_sz if b else None,
            "bids": (b.bids[:n] if b and b.bids else None),
            "asks": (b.asks[:n] if b and b.asks else None),
            "vol_1s": round(self.volume(1_000), 6),
            "vol_10s": round(self.volume(10_000), 6),
            "venues": {
                v: {
                    "price": vq.price,
                    "bid": vq.bid,
                    "ask": vq.ask,
                    "age_ms": t - vq.ts_ms,
                    "bids": (vq.bids[:n] if vq.bids else None),
                    "asks": (vq.asks[:n] if vq.asks else None),
                }
                for v, vq in self.venues.items()
            },
        }
