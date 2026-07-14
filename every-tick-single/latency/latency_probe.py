"""Baseline latency probe — run inside a cluster pod.

Measures every hop of the current signal->order path with per-stage breakdown:
  1. clock offset vs Binance + CLOB server time
  2. REST timing breakdown (DNS / TCP / TLS / TTFB / total) for every endpoint
     the bots actually hit
  3. POST /order round-trip proxy (unauthenticated -> origin rejects, but the
     network path is the real one)
  4. Binance aggTrade WS delivery delay (server trade ts vs local arrival)
  5. Polymarket CLOB market WS delivery delay (server ts vs local arrival)
  6. Polymarket RTDS WS delivery delay
  7. EIP-712 order signing CPU benchmark (dummy key, never posted)
  8. fav_taker sequential eval-chain simulation (the real current hot path)

Output: single JSON blob on stdout.
"""
import asyncio
import json
import socket
import ssl
import statistics as st
import time
import urllib.request

import websockets

OUT = {"probe_ts": time.time(), "samples": {}}
UA = {"User-Agent": "latency-probe"}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def summary(xs):
    if not xs:
        return None
    return {"n": len(xs), "min": round(min(xs), 1), "median": round(st.median(xs), 1),
            "p90": round(pct(xs, 0.90), 1), "max": round(max(xs), 1)}


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


# ── 1. clock offset ──────────────────────────────────────────────────────────
def clock_offset():
    out = {}
    for name, url, key in [
        ("binance", "https://api.binance.com/api/v3/time", "serverTime"),
    ]:
        offs = []
        for _ in range(5):
            t0 = time.time()
            sv = http_get(url)[key] / 1000.0
            t1 = time.time()
            offs.append((t0 + t1) / 2 - sv)  # local - server, RTT/2 midpoint
        out[name + "_offset_ms"] = round(st.median(offs) * 1000, 1)
    OUT["clock"] = out


# ── 2. staged REST breakdown ─────────────────────────────────────────────────
def staged_get(host, path, n=12, method="GET", body=None, extra_headers=""):
    """raw socket HTTP/1.1 one request per connection -> full cold-path breakdown."""
    dns, tcp, tls, ttfb, total = [], [], [], [], []
    for _ in range(n):
        t0 = time.time()
        addr = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4][0]
        t1 = time.time()
        s = socket.create_connection((addr, 443), timeout=10)
        t2 = time.time()
        ctx = ssl.create_default_context()
        w = ctx.wrap_socket(s, server_hostname=host)
        t3 = time.time()
        payload = body.encode() if body else b""
        req = (f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: latency-probe\r\n"
               f"Accept: application/json\r\n{extra_headers}"
               f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n").encode() + payload
        w.sendall(req)
        w.recv(1)
        t4 = time.time()
        try:
            while w.recv(65536):
                pass
        except Exception:
            pass
        t5 = time.time()
        w.close()
        dns.append((t1 - t0) * 1e3); tcp.append((t2 - t1) * 1e3); tls.append((t3 - t2) * 1e3)
        ttfb.append((t4 - t3) * 1e3); total.append((t5 - t0) * 1e3)
    return {"dns_ms": summary(dns), "tcp_ms": summary(tcp), "tls_ms": summary(tls),
            "ttfb_ms": summary(ttfb), "total_ms": summary(total)}


def warm_get(url, n=15):
    """keep-alive session -> the warm-path number (what a persistent session gets)."""
    import http.client
    from urllib.parse import urlparse
    u = urlparse(url)
    conn = http.client.HTTPSConnection(u.netloc, timeout=10)
    ts = []
    for i in range(n):
        t0 = time.time()
        conn.request("GET", u.path + ("?" + u.query if u.query else ""), headers=UA)
        r = conn.getresponse(); r.read()
        ts.append((time.time() - t0) * 1e3)
    conn.close()
    return summary(ts[1:])  # drop the connect-carrying first


def rest_suite(tokens):
    r = {}
    r["clob_price_cold"] = staged_get("clob.polymarket.com", f"/price?token_id={tokens['btc_up']}&side=BUY", n=8)
    r["clob_price_warm"] = warm_get(f"https://clob.polymarket.com/price?token_id={tokens['btc_up']}&side=BUY")
    r["clob_time_warm"] = warm_get("https://clob.polymarket.com/time")
    r["gamma_markets_warm"] = warm_get("https://gamma-api.polymarket.com/markets?limit=1")
    r["binance_ticker_cold"] = staged_get("api.binance.com", "/api/v3/ticker/price?symbol=SOLUSDT", n=8)
    r["binance_ticker_warm"] = warm_get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT")
    r["binance_vision_ticker_warm"] = warm_get("https://data-api.binance.vision/api/v3/ticker/price?symbol=SOLUSDT")
    r["binance_klines_warm"] = warm_get("https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1m&limit=40")
    # order POST path proxy: unauthenticated POST hits origin and gets rejected
    r["clob_order_post_reject"] = staged_get(
        "clob.polymarket.com", "/order", n=8, method="POST", body='{"probe":true}',
        extra_headers="Content-Type: application/json\r\n")
    OUT["rest"] = r


# ── live market tokens ───────────────────────────────────────────────────────
def live_tokens():
    now = int(time.time())
    ws = now - now % 300
    toks = {}
    for coin in ("btc", "sol"):
        d = http_get(f"https://gamma-api.polymarket.com/markets?slug={coin}-updown-5m-{ws}")
        pair = json.loads(d[0]["clobTokenIds"])
        toks[f"{coin}_up"], toks[f"{coin}_down"] = pair[0], pair[1]
    return toks


# ── 4-6. WS delivery delays ──────────────────────────────────────────────────
async def binance_ws_delay(seconds=60):
    delays, gaps = [], []
    last = None
    url = "wss://stream.binance.com:9443/ws/solusdt@aggTrade"
    t0c = time.time()
    async with websockets.connect(url, ping_interval=20) as ws:
        connect_ms = (time.time() - t0c) * 1e3
        end = time.time() + seconds
        while time.time() < end:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            arr = time.time()
            m = json.loads(raw)
            if m.get("T"):
                delays.append((arr - m["T"] / 1000.0) * 1e3)
                if last is not None:
                    gaps.append((arr - last) * 1e3)
                last = arr
    return {"connect_ms": round(connect_ms, 1), "delivery_ms": summary(delays),
            "inter_msg_gap_ms": summary(gaps)}


async def clob_ws_delay(tokens, seconds=60):
    delays, counts = [], {"book": 0, "price_change": 0, "other": 0}
    url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    t0c = time.time()
    async with websockets.connect(url, ping_interval=10) as ws:
        connect_ms = (time.time() - t0c) * 1e3
        sub = {"type": "market", "assets_ids": [tokens["btc_up"], tokens["btc_down"],
                                                tokens["sol_up"], tokens["sol_down"]]}
        await ws.send(json.dumps(sub))
        end = time.time() + seconds
        while time.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                break
            arr = time.time()
            try:
                evs = json.loads(raw)
            except Exception:
                continue
            if isinstance(evs, dict):
                evs = [evs]
            for ev in evs:
                et = ev.get("event_type", "?")
                counts[et if et in counts else "other"] = counts.get(et if et in counts else "other", 0) + 1
                ts = ev.get("timestamp")
                if ts:
                    delays.append((arr - float(ts) / 1000.0) * 1e3)
    return {"connect_ms": round(connect_ms, 1), "delivery_ms": summary(delays), "events": counts}


async def rtds_ws_delay(seconds=45):
    url = "wss://ws-live-data.polymarket.com"
    delays = []
    t0c = time.time()
    async with websockets.connect(url, ping_interval=10) as ws:
        connect_ms = (time.time() - t0c) * 1e3
        await ws.send(json.dumps({"action": "subscribe", "subscriptions": [
            {"topic": "crypto_prices", "type": "update", "filters": "{\"symbol\":\"solusdt\"}"}]}))
        end = time.time() + seconds
        while time.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                break
            arr = time.time()
            try:
                m = json.loads(raw)
            except Exception:
                continue
            p = m.get("payload") or {}
            ts = p.get("timestamp") or m.get("timestamp")
            if ts:
                delays.append((arr - float(ts) / 1000.0) * 1e3)
    return {"connect_ms": round(connect_ms, 1), "delivery_ms": summary(delays)}


# ── 7. signing benchmark ─────────────────────────────────────────────────────
def signing_bench(tokens):
    from py_clob_client_v2 import ClobClient, OrderArgs
    key = "0x" + "11" * 32  # throwaway; sign-only, never posted
    c = ClobClient(host="https://clob.polymarket.com", key=key, chain_id=137)
    ts = []
    tok = tokens["btc_up"]
    for i in range(8):
        t0 = time.time()
        c.create_order(OrderArgs(token_id=tok, price=0.5, size=5.0, side="BUY", expiration=0))
        ts.append((time.time() - t0) * 1e3)
    return {"first_call_ms": round(ts[0], 1), "warm_sign_ms": summary(ts[1:])}


# ── 8. fav_taker eval chain (the real current hot path) ─────────────────────
def eval_chain(tokens):
    ts = {}
    t0 = time.time()
    http_get("https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1m&limit=40")
    ts["klines_ms"] = (time.time() - t0) * 1e3
    t0 = time.time()
    http_get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT")
    ts["spot_ms"] = (time.time() - t0) * 1e3
    t0 = time.time()
    now = int(time.time()); ws = now - now % 300
    http_get(f"https://gamma-api.polymarket.com/markets?slug=sol-updown-5m-{ws}")
    ts["gamma_ms"] = (time.time() - t0) * 1e3
    t0 = time.time()
    http_get(f"https://clob.polymarket.com/price?token_id={tokens['sol_up']}&side=BUY")
    ts["clob_price_ms"] = (time.time() - t0) * 1e3
    ts["chain_total_ms"] = sum(ts.values())
    return {k: round(v, 1) for k, v in ts.items()}


async def main():
    clock_offset()
    toks = live_tokens()
    rest_suite(toks)
    # run the three WS probes concurrently
    b, c, r = await asyncio.gather(
        binance_ws_delay(60), clob_ws_delay(toks, 60), rtds_ws_delay(45),
        return_exceptions=True)
    OUT["binance_ws"] = b if not isinstance(b, Exception) else {"error": str(b)}
    OUT["clob_ws"] = c if not isinstance(c, Exception) else {"error": str(c)}
    OUT["rtds_ws"] = r if not isinstance(r, Exception) else {"error": str(r)}
    try:
        OUT["signing"] = signing_bench(toks)
    except Exception as e:
        OUT["signing"] = {"error": repr(e)}
    # run eval chain 3x, keep each
    OUT["fav_eval_chain"] = [eval_chain(toks) for _ in range(3)]
    print(json.dumps(OUT))


if __name__ == "__main__":
    asyncio.run(main())
