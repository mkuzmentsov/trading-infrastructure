"""Custom multi-exchange aggregate feed — drop-in replacement for the single-
venue Binance lead feed.

Runs WS trade streams from 5 venues (Binance, Coinbase, Kraken, OKX, Bitstamp),
self-calibrates each venue's persistent offset from the cross-venue median (the
USDT/USD basis + spread) via a slow EMA, then publishes the MEDIAN of the aligned
prices — which filters single-venue noise the way Chainlink's own index does.

The aggregate is pushed into ``binance_state`` (same object the rest of the bot
reads), so every downstream consumer — ``binance_price``, ``price_divergence``
(fast-vs-Chainlink lead signal in math_signal), ``best_price`` in maker_rebate —
transparently uses the clean aggregate instead of raw Binance. No downstream
changes. Selected via ``PRICE_LEAD_SOURCE=aggregate`` (else run_binance_ws runs).

Motivation: the PM RTDS Chainlink resolution feed lags the real market ~12s
(measured). A noise-filtered real-time aggregate is a strictly better "fast
reference" than one exchange, which single-venue noise makes 70% head-fakes.
"""
from __future__ import annotations
import asyncio
import json
import statistics
import time

import websockets

from config import log
from core.binance_ws import binance_state

VENUES = ["binance", "coinbase", "kraken", "okx", "bitstamp"]

SUBS = {
    "binance":  ("wss://stream.binance.com:9443/ws/btcusdt@trade", None),
    "coinbase": ("wss://ws-feed.exchange.coinbase.com",
                 json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]})),
    "kraken":   ("wss://ws.kraken.com",
                 json.dumps({"event": "subscribe", "pair": ["XBT/USD"], "subscription": {"name": "trade"}})),
    "okx":      ("wss://ws.okx.com:8443/ws/v5/public",
                 json.dumps({"op": "subscribe", "args": [{"channel": "trades", "instId": "BTC-USDT"}]})),
    "bitstamp": ("wss://ws.bitstamp.net",
                 json.dumps({"event": "bts:subscribe", "data": {"channel": "live_trades_btcusd"}})),
}


def _parse(venue: str, m: str):
    try:
        d = json.loads(m)
    except Exception:
        return None
    try:
        if venue == "binance":
            return float(d["p"])
        if venue == "coinbase":
            return float(d["price"]) if d.get("type") == "ticker" and d.get("price") else None
        if venue == "kraken":
            if isinstance(d, list) and len(d) > 1 and isinstance(d[1], list):
                return float(d[1][-1][0])
            return None
        if venue == "okx":
            data = d.get("data")
            return float(data[0]["px"]) if data else None
        if venue == "bitstamp":
            return float(d["data"]["price"]) if d.get("event") == "trade" else None
    except Exception:
        return None
    return None


_px: dict[str, float] = {}
_ts: dict[str, float] = {}
_offset: dict[str, float] = {}


def _recalc_offset(venue: str) -> None:
    now = time.time()
    fresh = {v: _px[v] for v in _px if now - _ts.get(v, 0) < 10}
    if len(fresh) < 3:
        return
    med = statistics.median(fresh.values())
    cur = _px[venue] - med
    prev = _offset.get(venue, cur)
    _offset[venue] = 0.98 * prev + 0.02 * cur  # slow EMA of the venue basis


def aggregate(max_age: float = 10.0):
    """Median of fresh, offset-aligned venue prices (>=3 venues) or None."""
    now = time.time()
    aligned = [_px[v] - _offset.get(v, 0.0) for v in _px if now - _ts.get(v, 0) < max_age]
    return statistics.median(aligned) if len(aligned) >= 3 else None


async def _feed(venue: str) -> None:
    url, sub = SUBS[venue]
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, close_timeout=5) as ws:
                if sub:
                    await ws.send(sub)
                async for m in ws:
                    p = _parse(venue, m)
                    if p and p > 0:
                        _px[venue] = p
                        _ts[venue] = time.time()
                        _recalc_offset(venue)
        except Exception as exc:
            log.debug("agg feed %s reconnect: %s", venue, exc)
            await asyncio.sleep(2)


async def run_agg_ws() -> None:
    """Launch all venue feeds and push the aggregate into binance_state."""
    log.info("agg_ws: custom 5-venue aggregate feed ACTIVE (replaces Binance lead)")
    for v in VENUES:
        asyncio.create_task(_feed(v), name=f"agg_{v}")
    last_log = 0.0
    while True:
        p = aggregate()
        if p:
            binance_state._record(time.time(), p)
            if time.time() - last_log > 60:
                last_log = time.time()
                fresh = sum(1 for v in _px if time.time() - _ts.get(v, 0) < 10)
                log.info("agg_ws: price=%.1f venues_fresh=%d offsets=%s",
                         p, fresh, {v: round(_offset.get(v, 0), 1) for v in VENUES if v in _px})
        await asyncio.sleep(0.5)
