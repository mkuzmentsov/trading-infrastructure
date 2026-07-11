"""Binance spot feed: @trade (price + volume + aggressor side) and @bookTicker
(best bid/ask + sizes). One combined WS connection for all configured symbols.
A recv-timeout watchdog force-reconnects if the stream goes silent."""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

from .base import VenueFeed

log = logging.getLogger("agg.binance")

BASE = "wss://stream.binance.com:9443/stream?streams="


def _depth_stream_levels(requested: int) -> int:
    """Binance partial-depth streams exist only at 5, 10, 20 levels."""
    for n in (5, 10, 20):
        if requested <= n:
            return n
    return 20


class BinanceFeed(VenueFeed):
    name = "binance"

    def _url(self) -> str:
        dn = _depth_stream_levels(self.depth_levels)
        streams = []
        for s in self.symbols:
            streams += [f"{s}@trade", f"{s}@bookTicker", f"{s}@depth{dn}@100ms"]
        return BASE + "/".join(streams)

    async def run(self) -> None:
        url = self._url()
        async with websockets.connect(url, ping_interval=20, ping_timeout=20,
                                      close_timeout=5, max_queue=None) as ws:
            log.info("binance connected: %d symbols, depth%d",
                     len(self.symbols), _depth_stream_levels(self.depth_levels))
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    # silence on a high-rate feed = dead; drop and reconnect
                    raise ConnectionError("binance recv timeout")
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # combined stream wraps: {"stream":"btcusdt@depth10@100ms","data":{...}}
                stream = msg.get("stream", "")
                data = msg.get("data", msg)
                self._handle(stream, data)

    def _handle(self, stream: str, d: dict) -> None:
        # partial-depth payloads carry no symbol -> derive it from the stream name
        sym = (d.get("s") or (stream.split("@", 1)[0] if stream else "")).lower()
        if not sym:
            return
        st = self.state(sym)
        if "@depth" in stream:
            try:
                bids = [[float(p), float(q)] for p, q in d.get("bids", [])]
                asks = [[float(p), float(q)] for p, q in d.get("asks", [])]
            except (ValueError, TypeError):
                return
            st.on_depth(self.name, bids, asks)
        elif d.get("e") == "trade":
            try:
                price = float(d["p"]); qty = float(d["q"])
            except (KeyError, ValueError):
                return
            side = "sell" if d.get("m") else "buy"  # m=buyer-is-maker -> seller aggressor
            st.on_trade(self.name, price, qty, side)
        elif "b" in d and "a" in d:  # bookTicker
            try:
                st.on_book(self.name, float(d["b"]), float(d["B"]),
                           float(d["a"]), float(d["A"]))
            except (KeyError, ValueError):
                return
