#!/usr/bin/env python3
"""Real-time multi-exchange BTC aggregate — an 'unlagged Chainlink replica'.
WS trade feeds from Binance, Coinbase, Kraken, OKX, Bitstamp. Each venue's
persistent offset from the cross-venue median (USDT/USD basis + spread) is
tracked by EMA and subtracted, then the aggregate = MEDIAN of aligned prices
(median filters single-venue noise, like Chainlink — the 30%-echo lesson).

Use standalone: `Aggregator()` then read `.price()`; or run this file to print
the live aggregate vs each venue.
"""
import asyncio, json, time, statistics
import websockets

VENUES = ["binance", "coinbase", "kraken", "okx", "bitstamp"]

SUBS = {
    "binance":  ("wss://stream.binance.com:9443/ws/btcusdt@trade", None),
    "coinbase": ("wss://ws-feed.exchange.coinbase.com",
                 json.dumps({"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker"]})),
    "kraken":   ("wss://ws.kraken.com",
                 json.dumps({"event":"subscribe","pair":["XBT/USD"],"subscription":{"name":"trade"}})),
    "okx":      ("wss://ws.okx.com:8443/ws/v5/public",
                 json.dumps({"op":"subscribe","args":[{"channel":"trades","instId":"BTC-USDT"}]})),
    "bitstamp": ("wss://ws.bitstamp.net",
                 json.dumps({"event":"bts:subscribe","data":{"channel":"live_trades_btcusd"}})),
}

def parse(venue, m):
    try:
        d = json.loads(m)
    except Exception:
        return None
    try:
        if venue == "binance":  return float(d["p"])
        if venue == "coinbase": return float(d["price"]) if d.get("type")=="ticker" and d.get("price") else None
        if venue == "kraken":
            if isinstance(d, list) and len(d) > 1 and isinstance(d[1], list):
                return float(d[1][-1][0])  # last trade price
            return None
        if venue == "okx":
            data = d.get("data"); return float(data[0]["px"]) if data else None
        if venue == "bitstamp":
            return float(d["data"]["price"]) if d.get("event")=="trade" else None
    except Exception:
        return None
    return None

class Aggregator:
    def __init__(self):
        self.px = {}          # venue -> latest raw price
        self.ts = {}          # venue -> last update time
        self.offset = {}      # venue -> EMA(price - median)
        self._tasks = []
    async def _feed(self, venue):
        url, sub = SUBS[venue]
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, close_timeout=5) as ws:
                    if sub: await ws.send(sub)
                    async for m in ws:
                        p = parse(venue, m)
                        if p and p > 0:
                            self.px[venue] = p; self.ts[venue] = time.time()
                            self._recalc_offset(venue)
            except Exception:
                await asyncio.sleep(2)
    def _recalc_offset(self, venue):
        fresh = {v: self.px[v] for v in self.px if time.time()-self.ts.get(v,0) < 10}
        if len(fresh) < 3: return
        med = statistics.median(fresh.values())
        cur = self.px[venue] - med
        prev = self.offset.get(venue, cur)
        self.offset[venue] = 0.98*prev + 0.02*cur   # slow EMA of the basis
    def price(self, max_age=10.0):
        now = time.time()
        aligned = [self.px[v]-self.offset.get(v,0.0) for v in self.px if now-self.ts.get(v,0) < max_age]
        return statistics.median(aligned) if len(aligned) >= 3 else None
    def detail(self, max_age=10.0):
        now = time.time()
        return {v: (round(self.px[v],1), round(self.offset.get(v,0),1), round(now-self.ts.get(v,0),1))
                for v in VENUES if v in self.px}
    def start(self):
        for v in VENUES:
            self._tasks.append(asyncio.ensure_future(self._feed(v)))

async def _demo():
    agg = Aggregator(); agg.start()
    for _ in range(40):
        await asyncio.sleep(2)
        p = agg.price()
        print(f"AGG={p if p is None else round(p,1)}  venues={agg.detail()}")

if __name__ == "__main__":
    asyncio.run(_demo())
