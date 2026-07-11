#!/usr/bin/env python3
"""Realtime executability monitor (MEASUREMENT ONLY, no trading).

Continuously (~1 row/sec, whole bar) aligns three things for the live btc 5m
up/down market:
  - AGG   : our fast 5-venue aggregate (unlagged Chainlink replica)  [aggregator.py]
  - CL    : PM RTDS Chainlink price (the lagged resolution truth)
  - BOOK  : up/down token best bid/ask + sizes, from the PM CLOB market WS

Answers two questions:
  (1) Does AGG lead CL, and by how much? (agg vs chainlink over time)
  (2) Can we LEVER the delay? i.e. when AGG has moved a side into the money but
      the lagged book hasn't repriced, is that side's ASK still cheap enough to
      lift for positive EV before the bar closes?

Writes jsonl to latency/rtmonitor.jsonl. Run: python3 latency/rtmonitor.py
"""
import asyncio, json, time, sys, os, urllib.request
import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aggregator import Aggregator

RTDS_WS = "wss://ws-live-data.polymarket.com"
PM_WS   = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA   = "https://gamma-api.polymarket.com/markets"
OUT     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rtmonitor.jsonl")
ROW_EVERY = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

st = {"chainlink": None, "chainlink_ts": 0.0}
# up/down BBO, keyed by token id -> (bid, bid_sz, ask, ask_sz, ts)
book = {}

def log(ev):
    with open(OUT, "a") as f:
        f.write(json.dumps(ev) + "\n")

def _u(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8)

# ---------------- RTDS Chainlink ----------------
def _rtds_value(msg):
    """Latest chainlink price from an RTDS message. Handles both the initial
    snapshot (payload.data[] list) and ongoing single-point deltas (payload.value)."""
    if isinstance(msg, list):
        for item in reversed(msg):
            v = _rtds_value(item)
            if v is not None: return v
        return None
    if not isinstance(msg, dict): return None
    pl = msg.get("payload")
    if isinstance(pl, str):
        try: pl = json.loads(pl)
        except Exception: pl = {}
    if not isinstance(pl, dict): pl = {}
    data = pl.get("data")
    if data is None and isinstance(msg.get("data"), list): data = msg.get("data")
    if isinstance(data, list) and data:
        try: return float(data[-1].get("value"))
        except Exception: pass
    try:
        v = float(pl.get("value") or 0.0)
        if v > 0: return v
    except Exception: pass
    return None

async def rtds():
    # The RTDS stream can burst then go silent on a live connection while TCP
    # stays up; a plain `async for` then hangs forever. So: no library ping,
    # recv with a timeout, app-level PING on quiet, force-reconnect if stalled.
    sub = json.dumps({"action": "subscribe", "subscriptions": [
        {"topic": "crypto_prices_chainlink", "type": "*",
         "filters": json.dumps({"symbol": "btc/usd"}, separators=(",", ":"))}]})
    while True:
        try:
            async with websockets.connect(RTDS_WS, ping_interval=None, ping_timeout=None) as ws:
                await ws.send(sub)
                quiet = 0
                while True:
                    try:
                        m = await asyncio.wait_for(ws.recv(), timeout=3)
                    except asyncio.TimeoutError:
                        quiet += 1
                        if quiet >= 3:  # ~9s silent -> reconnect fresh
                            break
                        try: await ws.send("PING")
                        except Exception: break
                        continue
                    quiet = 0
                    try: d = json.loads(m)
                    except Exception: continue
                    v = _rtds_value(d)
                    if v is not None:
                        st["chainlink"] = v; st["chainlink_ts"] = time.time()
        except Exception:
            await asyncio.sleep(2)

# ---------------- PM up/down book ----------------
def _top(bids, asks):
    bb = max((float(b["price"]) for b in bids), default=0.0)
    aa = min((float(a["price"]) for a in asks), default=1.0)
    bsz = sum(float(b["size"]) for b in bids if float(b["price"]) == bb) if bb else 0.0
    asz = sum(float(a["size"]) for a in asks if float(a["price"]) == aa) if aa < 1 else 0.0
    return bb, bsz, aa, asz

def _apply(tok, bid, bsz, ask, asz):
    if bid and ask <= 1 and bid > ask:  # crossed -> mid
        mid = round((bid + ask) / 2, 3); bid = ask = mid
    book[tok] = (bid, bsz, ask, asz, time.time())

async def pm_book(get_tokens):
    """Subscribe to current bar tokens; resubscribe when they change."""
    cur_tokens = []
    while True:
        toks = get_tokens()
        if not toks:
            await asyncio.sleep(1); continue
        cur_tokens = toks
        try:
            async with websockets.connect(PM_WS, ping_interval=20, ping_timeout=30) as ws:
                await ws.send(json.dumps({"type": "market", "assets_ids": toks,
                                          "custom_feature_enabled": True}))
                while True:
                    if get_tokens() != cur_tokens:
                        break  # boundary -> reconnect with new tokens
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        await ws.send("PING"); continue
                    try:
                        msgs = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(msgs, list): msgs = [msgs]
                    for msg in msgs:
                        et = msg.get("event_type"); aid = msg.get("asset_id", "")
                        if et == "book":
                            bb, bsz, aa, asz = _top(msg.get("bids", []), msg.get("asks", []))
                            _apply(aid, bb, bsz, aa, asz)
                        elif et == "best_bid_ask":
                            prev = book.get(aid, (0, 0, 1, 0, 0))
                            _apply(aid, float(msg.get("best_bid", 0) or 0), prev[1],
                                   float(msg.get("best_ask", 1) or 1), prev[3])
                        elif et == "price_change":
                            for ch in msg.get("price_changes", []):
                                a = ch.get("asset_id", ""); prev = book.get(a, (0, 0, 1, 0, 0))
                                _apply(a, float(ch.get("best_bid", 0) or 0), prev[1],
                                       float(ch.get("best_ask", 1) or 1), prev[3])
        except Exception:
            await asyncio.sleep(2)

# ---------------- market tokens per bar ----------------
_market = {"ws": 0, "tokens": [], "open": None}
def gamma_tokens(ws_ts):
    try:
        d = json.loads(_u(GAMMA + f"?slug=btc-updown-5m-{ws_ts}").read())
        if d: return json.loads(d[0]["clobTokenIds"])  # [UP, DOWN]
    except Exception: pass
    return []

async def market_tracker():
    while True:
        now = time.time(); cur = int(now // 300) * 300
        if _market["ws"] != cur:
            toks = gamma_tokens(cur)
            _market.update(ws=cur, tokens=toks, open=st["chainlink"])
            log({"ev": "bar_open", "ws": cur, "chainlink_open": st["chainlink"], "t": round(now, 2)})
        elif _market["open"] is None and st["chainlink"]:
            _market["open"] = st["chainlink"]
        await asyncio.sleep(0.5)

def get_tokens(): return _market["tokens"]

# ---------------- sampler ----------------
async def sampler():
    agg = Aggregator(); agg.start()
    while True:
        await asyncio.sleep(ROW_EVERY)
        now = time.time(); cur = int(now // 300) * 300
        toks = _market["tokens"]
        if len(toks) < 2: continue
        up, dn = toks[0], toks[1]
        ub = book.get(up); db = book.get(dn)
        a = agg.price()
        row = {
            "ev": "s", "t": round(now, 2), "ws": cur,
            "secs_left": round(cur + 300 - now, 1),
            "agg": None if a is None else round(a, 2),
            "cl": st["chainlink"], "cl_age": round(now - st["chainlink_ts"], 2),
            "open": _market["open"],
            "up_bid": ub[0] if ub else None, "up_ask": ub[2] if ub else None,
            "up_bid_sz": ub[1] if ub else None, "up_ask_sz": ub[3] if ub else None,
            "dn_bid": db[0] if db else None, "dn_ask": db[2] if db else None,
            "dn_bid_sz": db[1] if db else None, "dn_ask_sz": db[3] if db else None,
        }
        log(row)

async def main():
    print(f"rtmonitor: writing {OUT}  (row every {ROW_EVERY}s)")
    await asyncio.gather(rtds(), market_tracker(), pm_book(get_tokens), sampler())

if __name__ == "__main__":
    asyncio.run(main())
