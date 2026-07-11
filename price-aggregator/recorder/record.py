#!/usr/bin/env python3
"""Delay recorder (MEASUREMENT ONLY). Subscribes to three live feeds and logs
aligned rows so we can measure whether our aggregate price LEADS the Polymarket
RTDS Chainlink resolution feed, and whether the up/down book stays stale long
enough to leverage:

  AGG   - our price-aggregator service WS  (env AGG_WS, unlagged aggregate)
  CL    - PM RTDS Chainlink price          (the lagged resolution truth)
  BOOK  - up/down token best bid/ask+size  (PM CLOB market WS)

Row (~ROW_MS cadence) -> data/delay.jsonl:
  {t, ws, secs_left, agg, agg_age, cl, cl_age, open,
   up_bid/ask(+sz), dn_bid/ask(+sz),                     # BBO scalars
   up_bids/up_asks/dn_bids/dn_asks,                      # PM ladders top-DEPTH [[px,sz]..]
   agg_bids/agg_asks}                                    # our Binance depth via the agg svc

Env: AGG_WS (default ws://price-aggregator:8080), SYMBOL (btcusdt),
     COIN (btc), RTDS_SYMBOL (btc/usd), ROW_MS (250),
     DEPTH_LEVELS (10), OUT (data/delay.jsonl)
"""
import asyncio, json, os, time, urllib.request
import websockets

AGG_WS      = os.getenv("AGG_WS", "ws://price-aggregator:8080")
SYMBOL      = os.getenv("SYMBOL", "btcusdt")
COIN        = os.getenv("COIN", "btc")
RTDS_SYMBOL = os.getenv("RTDS_SYMBOL", "btc/usd")
ROW_MS      = int(os.getenv("ROW_MS", "250"))
DEPTH       = int(os.getenv("DEPTH_LEVELS", "10"))
OUT         = os.getenv("OUT", "data/delay.jsonl")

RTDS_WS = "wss://ws-live-data.polymarket.com"
PM_WS   = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA   = "https://gamma-api.polymarket.com/markets"

st = {"agg": None, "agg_ts": 0.0, "cl": None, "cl_ts": 0.0,
      "agg_bids": None, "agg_asks": None}
# token -> {"bids": {px: sz}, "asks": {px: sz}, "ts": t}
book = {}
_market = {"ws": 0, "tokens": [], "open": None}


def log(ev):
    with open(OUT, "a") as f:
        f.write(json.dumps(ev) + "\n")


def _u(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8)


# ---------------- our aggregate service ----------------
async def agg_feed():
    while True:
        try:
            async with websockets.connect(AGG_WS, ping_interval=20) as ws:
                await ws.send(json.dumps({"op": "subscribe", "symbols": [SYMBOL]}))
                async for raw in ws:
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("symbol") == SYMBOL and m.get("price"):
                        st["agg"] = float(m["price"]); st["agg_ts"] = time.time()
                        st["agg_bids"] = m.get("bids"); st["agg_asks"] = m.get("asks")
        except Exception:
            await asyncio.sleep(2)


# ---------------- RTDS Chainlink (watchdog reconnect) ----------------
def _rtds_value(msg):
    if isinstance(msg, list):
        for item in reversed(msg):
            v = _rtds_value(item)
            if v is not None:
                return v
        return None
    if not isinstance(msg, dict):
        return None
    pl = msg.get("payload")
    if isinstance(pl, str):
        try: pl = json.loads(pl)
        except Exception: pl = {}
    if not isinstance(pl, dict):
        pl = {}
    data = pl.get("data")
    if data is None and isinstance(msg.get("data"), list):
        data = msg.get("data")
    if isinstance(data, list) and data:
        try: return float(data[-1].get("value"))
        except Exception: pass
    try:
        v = float(pl.get("value") or 0.0)
        if v > 0:
            return v
    except Exception:
        pass
    return None


async def rtds():
    sub = json.dumps({"action": "subscribe", "subscriptions": [
        {"topic": "crypto_prices_chainlink", "type": "*",
         "filters": json.dumps({"symbol": RTDS_SYMBOL}, separators=(",", ":"))}]})
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
                        if quiet >= 3:
                            break
                        try: await ws.send("PING")
                        except Exception: break
                        continue
                    quiet = 0
                    try: d = json.loads(m)
                    except Exception: continue
                    v = _rtds_value(d)
                    if v is not None:
                        st["cl"] = v; st["cl_ts"] = time.time()
        except Exception:
            await asyncio.sleep(2)


# ---------------- PM up/down book (full ladder) ----------------
def _ladder(tok):
    lb = book.get(tok)
    if lb is None:
        lb = {"bids": {}, "asks": {}, "ts": 0.0}
        book[tok] = lb
    return lb


def _snapshot(tok, bids, asks):
    """Replace the ladder from a full `book` event."""
    lb = _ladder(tok)
    lb["bids"] = {float(b["price"]): float(b["size"]) for b in bids if float(b["size"]) > 0}
    lb["asks"] = {float(a["price"]): float(a["size"]) for a in asks if float(a["size"]) > 0}
    lb["ts"] = time.time()


def _delta(tok, price, size, side):
    """Apply one `price_change` level update (size 0 removes the level)."""
    lb = _ladder(tok)
    side_key = "bids" if side == "BUY" else "asks" if side == "SELL" else None
    if side_key is None:
        return
    if size > 0:
        lb[side_key][price] = size
    else:
        lb[side_key].pop(price, None)
    lb["ts"] = time.time()


def _top_n(tok, n):
    """Return (bids, asks) as sorted top-n [[px, sz], ...] best-first."""
    lb = book.get(tok)
    if not lb:
        return None, None
    bids = sorted(lb["bids"].items(), key=lambda kv: -kv[0])[:n]
    asks = sorted(lb["asks"].items(), key=lambda kv: kv[0])[:n]
    return ([[p, s] for p, s in bids] or None, [[p, s] for p, s in asks] or None)


async def pm_book():
    cur = []
    while True:
        toks = _market["tokens"]
        if len(toks) < 2:
            await asyncio.sleep(1); continue
        cur = toks
        try:
            async with websockets.connect(PM_WS, ping_interval=20, ping_timeout=30) as ws:
                await ws.send(json.dumps({"type": "market", "assets_ids": toks,
                                          "custom_feature_enabled": True}))
                while True:
                    if _market["tokens"] != cur:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        await ws.send("PING"); continue
                    try:
                        msgs = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(msgs, list):
                        msgs = [msgs]
                    for msg in msgs:
                        et = msg.get("event_type"); aid = msg.get("asset_id", "")
                        if et == "book":
                            _snapshot(aid, msg.get("bids", []), msg.get("asks", []))
                        elif et == "price_change":
                            for ch in msg.get("price_changes", []):
                                try:
                                    _delta(ch.get("asset_id", ""), float(ch.get("price")),
                                           float(ch.get("size", 0) or 0),
                                           (ch.get("side") or "").upper())
                                except (TypeError, ValueError):
                                    continue
                        # best_bid_ask carries no ladder sizes -> rely on book+price_change
        except Exception:
            await asyncio.sleep(2)


def gamma_tokens(ws_ts):
    try:
        d = json.loads(_u(GAMMA + f"?slug={COIN}-updown-5m-{ws_ts}").read())
        if d:
            return json.loads(d[0]["clobTokenIds"])  # [UP, DOWN]
    except Exception:
        pass
    return []


async def market_tracker():
    while True:
        now = time.time(); cur = int(now // 300) * 300
        if _market["ws"] != cur:
            _market.update(ws=cur, tokens=gamma_tokens(cur), open=st["cl"])
            log({"ev": "bar_open", "ws": cur, "chainlink_open": st["cl"], "t": round(now, 2)})
        elif _market["open"] is None and st["cl"]:
            _market["open"] = st["cl"]
        await asyncio.sleep(0.5)


# ---------------- sampler ----------------
def _bbo(bids, asks):
    """(bid, bid_sz, ask, ask_sz) from top-n ladders."""
    bid = bids[0] if bids else [None, None]
    ask = asks[0] if asks else [None, None]
    return bid[0], bid[1], ask[0], ask[1]


async def sampler():
    while True:
        await asyncio.sleep(ROW_MS / 1000)
        now = time.time(); cur = int(now // 300) * 300
        toks = _market["tokens"]
        up_b = up_a = dn_b = dn_a = None
        if len(toks) >= 2:
            up_b, up_a = _top_n(toks[0], DEPTH)
            dn_b, dn_a = _top_n(toks[1], DEPTH)
        u_bid, u_bsz, u_ask, u_asz = _bbo(up_b, up_a)
        d_bid, d_bsz, d_ask, d_asz = _bbo(dn_b, dn_a)
        log({
            "ev": "s", "t": round(now, 3), "ws": cur,
            "secs_left": round(cur + 300 - now, 1),
            "agg": st["agg"], "agg_age": round(now - st["agg_ts"], 3) if st["agg_ts"] else None,
            "cl": st["cl"], "cl_age": round(now - st["cl_ts"], 3) if st["cl_ts"] else None,
            "open": _market["open"],
            # BBO scalars (back-compatible with the earlier analyzer)
            "up_bid": u_bid, "up_ask": u_ask, "up_bid_sz": u_bsz, "up_ask_sz": u_asz,
            "dn_bid": d_bid, "dn_ask": d_ask, "dn_bid_sz": d_bsz, "dn_ask_sz": d_asz,
            # full ladders, top-DEPTH, best-first [[px, sz], ...]
            "up_bids": up_b, "up_asks": up_a, "dn_bids": dn_b, "dn_asks": dn_a,
            # our aggregate's Binance depth (from the agg service)
            "agg_bids": st["agg_bids"], "agg_asks": st["agg_asks"],
        })


async def main():
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    print(f"recorder: AGG_WS={AGG_WS} symbol={SYMBOL} coin={COIN} -> {OUT} (row {ROW_MS}ms)", flush=True)
    await asyncio.gather(agg_feed(), rtds(), pm_book(), market_tracker(), sampler())


if __name__ == "__main__":
    asyncio.run(main())
