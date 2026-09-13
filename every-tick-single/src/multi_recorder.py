"""multi_recorder — 100ms multi-market recorder: CURRENT bar (kept until RESOLVED)
+ the NEXT N bars' pre-open books, all on one PM WS connection.

Why: the #1 leaderboard earner buys the NEXT bar's outcome at ~0.50 during the
final minute of the current bar — a window the single-market recorder never saw.
This records, per 100ms tick, one SNAP row PER TRACKED MARKET with an explicit
`role` so bars are trivially distinguishable:
  role=cur    live bar (t in [ws, end))
  role=post   after close, until gamma RESOLVES it → then a RES row + drop
  role=next1  the bar starting at cur.end        (pre-open book)
  role=next2  the bar starting at cur.end+BAR    (pre-open book)

Rows: BAR (once per market discovered), SNAP {ws, role, tl, spot/lead (Binance),
ub/ua/db/da + sizes, cumulative per-market volume vol/volsh, trd prints},
RES {ws, win} when gamma resolution lands. Env: MREC_AHEAD(2) SNAPSHOT_MS(100)
RAW_LOG_DIR RETENTION_DAYS COIN. Own book state — shared pm_ws untouched.
"""
from __future__ import annotations

import asyncio, json, time, os, urllib.request
import websockets

from config import BAR_SECONDS, COIN, POLYMARKET_WS, log
from core.binance_ws import binance_state, run_binance_ws
from core.rtds import rtds_state, run_rtds
from core.gamma import (fetch_market_for_window, get_up_down_tokens,
                        grid_window_start, next_window_start, window_slug)
from ws_recorder import RotatingWriter, _seed_history

AHEAD = int(os.getenv("MREC_AHEAD", "3"))
SNAP_SECS = max(20, int(float(os.getenv("SNAPSHOT_MS", "100")))) / 1000.0
# RTDS symbol for this coin, e.g. "btc/usd".
RTDS_SYM = os.getenv("POLYMARKET_RTDS_SYMBOL", f"{COIN}/usd")
# ⚠️ MUST be twap_SIXTY. rtds.run_rtds() DEFAULTS to twap_thirty, which is the
# WRONG stream — all coins settle TWAP-60 (the live vacmaker derives this same
# topic from PM_TE_TWAP_WINDOW=60). Subscribing to the default would have
# recorded a settlement reference these markets do not use.
RTDS_TOPICS = ("crypto_prices_chainlink", "crypto_prices_twap_sixty")

# ── BINANCE RAW CAPTURE (added 2026-09-13, user: "add binance ws to the mrec,
# all the data we can potentially make use of") ─────────────────────────────
# Written to a SEPARATE hourly file `<coin>-brec*-YYYYMMDD-HH.jsonl.gz` so the
# existing mrec/mrecev parsers are untouched. Every row: {t: local arrival
# (4dp), ev:"BIN"|"BINF", s: stream name, m: raw payload}. Event-time truth on
# the venue we use as the settlement PROXY — pairs with `cl` for lead studies.
#   spot  : aggTrade (every print), bookTicker (top-of-book on every change),
#           depth@100ms (diff book), kline_1s (compact OHLCV)
#   futures: markPrice@1s (mark/index/funding), forceOrder (liquidations)
# Off unless BREC_SPOT_STREAMS is non-empty; the 15m/1h/4h/1d recorders leave
# it empty so only the 5m fleet captures (one connection per coin, no dupes).
BREC_SYMBOL = os.getenv("BREC_SYMBOL", f"{COIN}usdt").strip().lower()
BREC_SPOT = [s for s in os.getenv("BREC_SPOT_STREAMS", "").split(",") if s.strip()]
BREC_FUT = [s for s in os.getenv("BREC_FUT_STREAMS", "").split(",") if s.strip()]
BREC_SPOT_HOST = os.getenv("BREC_SPOT_HOST", "wss://stream.binance.com:9443")
BREC_FUT_HOST = os.getenv("BREC_FUT_HOST", "wss://fstream.binance.com")


def _rtds_latest(book):
    """(ts, value) of the newest tick for our symbol, or (None, None).
    ⚠️ rtds.ingest does NOT normalise case, so match case-insensitively."""
    d = book.get(RTDS_SYM)
    if not d:
        low = RTDS_SYM.lower()
        for k, v in book.items():
            if k.lower() == low:
                d = v
                break
    if not d:
        return None, None
    ts = max(d)
    return int(ts), d[ts]
# distinguish archives by bar length: btc-mrec (5m), btc-mrec1h, btc-mrec1d
_SUFFIX = {900: "15m", 3600: "1h", 14400: "4h", 86400: "1d"}.get(BAR_SECONDS, "")


class Mkt:
    def __init__(self, ws_ts: int, market: dict):
        up, down = get_up_down_tokens(market)
        self.ws = ws_ts; self.end = next_window_start(ws_ts)
        self.cid = market.get("conditionId", "")
        self.slug = market.get("slug") or ""
        self.q = market.get("question", "")
        self.up = up["token_id"]; self.down = down["token_id"]
        self.bids: dict[str, dict] = {self.up: {}, self.down: {}}
        self.asks: dict[str, dict] = {self.up: {}, self.down: {}}
        self.vol_sh = 0.0; self.vol_notl = 0.0
        self.hash: dict[str, str] = {}       # token -> last venue book hash (WS)
        self.tick: dict[str, str] = {}       # token -> last tick_size_change value
        self.trades: list = []          # unemitted prints
        self.resolved: str | None = None
        self.res_poll_at = 0.0

    def depth(self, tok: str, n: int = 10):
        b = sorted(self.bids[tok].items(), reverse=True)[:n]
        a = sorted(self.asks[tok].items())[:n]
        f = lambda side: [[round(p, 3), round(s, 1)] for p, s in side]
        return f(b), f(a)

    def bbo(self, tok: str):
        b = self.bids[tok]; a = self.asks[tok]
        bb = max(b) if b else None; ba = min(a) if a else None
        return (bb, b.get(bb, 0.0) if bb else 0.0, ba, a.get(ba, 0.0) if ba else 0.0)

    def role(self, now: float, cur_ws: int) -> str:
        if self.ws == cur_ws:
            return "cur" if now < self.end else "post"
        if now >= self.end:
            return "post"
        # count grid steps via next_window_start (DST-safe for daily windows,
        # where a step is 23h/25h twice a year)
        w, k = cur_ws, 0
        while w < self.ws and k < AHEAD + 2:
            w = next_window_start(w); k += 1
        return f"next{max(1, k)}"


class MultiRecorder:
    def __init__(self):
        self.mkts: dict[int, Mkt] = {}          # ws -> Mkt
        self.tok2m: dict[str, tuple[Mkt, str]] = {}   # token -> (mkt, "U"/"D")
        self.writer = RotatingWriter(os.getenv("RAW_LOG_DIR", "/app/logs/raw"),
                                     f"{COIN}-mrec{_SUFFIX}")
        # v2 (2026-09-01): raw WS event stream, verbatim + role-tagged
        self.evwriter = RotatingWriter(os.getenv("RAW_LOG_DIR", "/app/logs/raw"),
                                       f"{COIN}-mrecev{_SUFFIX}")
        self.last_ev_t = 0.0            # arrival time of last WS market event
        self.ev_n = 0                   # events this WS session
        self.ws_sess = 0                # WS session counter
        self.evq: list = []             # buffered raw events (drained async)
        self.bwriter = RotatingWriter(os.getenv("RAW_LOG_DIR", "/app/logs/raw"),
                                      f"{COIN}-brec{_SUFFIX}") if (BREC_SPOT or BREC_FUT) else None
        self.bq: list = []              # buffered binance rows
        self.b_msgs = 0                 # counter for the heartbeat
        self.resub = asyncio.Event()

    def _track(self, ws_ts: int, market: dict):
        m = Mkt(ws_ts, market)
        self.mkts[ws_ts] = m
        self.tok2m[m.up] = (m, "U"); self.tok2m[m.down] = (m, "D")
        asyncio.create_task(self.writer.write(
            {"t": round(time.time(), 3), "coin": COIN, "ws": ws_ts, "ev": "BAR",
             "cid": m.cid, "slug": m.slug, "q": m.q, "up": m.up, "down": m.down, "end": m.end}))
        self.resub.set()
        log.info("track ws=%s %s", ws_ts, m.q[:60])

    def _drop(self, ws_ts: int):
        m = self.mkts.pop(ws_ts, None)
        if m:
            self.tok2m.pop(m.up, None); self.tok2m.pop(m.down, None)
            self.resub.set()

    # ── market discovery: keep cur + AHEAD next tracked ──────────────────────
    async def discover_loop(self):
        while True:
            try:
                now = time.time()
                w = grid_window_start(now)
                for _ in range(0, AHEAD + 1):
                    if w not in self.mkts:
                        mk = await asyncio.to_thread(fetch_market_for_window, w)
                        if mk:
                            self._track(w, mk)
                    w = next_window_start(w)
            except Exception as exc:
                log.warning("discover: %s", exc)
            # long bars don't need a 2s discovery spin; nextN markets for the
            # daily series are only created ~1.5 days ahead anyway
            await asyncio.sleep(2.0 if BAR_SECONDS <= 3600 else 30.0)

    # ── resolution poll for post-close markets; drop once resolved ───────────
    async def resolve_loop(self):
        while True:
            await asyncio.sleep(2.0)
            now = time.time()
            for w, m in list(self.mkts.items()):
                if now < m.end + 3 or m.resolved or now < m.res_poll_at:
                    continue
                m.res_poll_at = now + 4.0
                try:
                    url = ("https://gamma-api.polymarket.com/markets?slug="
                           + window_slug(w) + "&closed=true")
                    d = json.loads(urllib.request.urlopen(
                        urllib.request.Request(url, headers={"User-Agent": "mrec"}),
                        timeout=8).read())
                    if d and d[0].get("closed"):
                        op = d[0]["outcomePrices"]
                        op = json.loads(op) if isinstance(op, str) else op
                        m.resolved = "UP" if str(op[0]) in ("1", "1.0") else "DOWN"
                        await self.writer.write(
                            {"t": round(now, 3), "coin": COIN, "ws": w, "ev": "RES", "slug": m.slug,
                             "win": m.resolved,
                             "post_secs": round(now - m.end, 1)})
                        self._drop(w)
                except Exception:
                    pass
                # safety give-up. 10min was enough for 5m markets, but hourly/
                # daily carry customLiveness=600: gamma flips closed=true only
                # ~10-11min after close, exactly when the old 600s cutoff had
                # already dropped the market -- zero RES rows in 52 archives.
                if now - m.end > (600 if BAR_SECONDS < 3600 else 1800) and w in self.mkts:
                    self._drop(w)

    # ── one PM WS for all tracked tokens ─────────────────────────────────────
    async def ws_loop(self):
        while True:
            toks = list(self.tok2m)
            if not toks:
                await asyncio.sleep(1.0); continue
            try:
                async with websockets.connect(POLYMARKET_WS, ping_interval=20,
                                              ping_timeout=30) as ws:
                    self.resub.clear()
                    self.ws_sess += 1; self.ev_n = 0
                    await ws.send(json.dumps({"type": "market", "assets_ids": toks,
                                              "custom_feature_enabled": True}))
                    log.info("WS subscribed %d tokens", len(toks))
                    while True:
                        if self.resub.is_set():
                            break                      # reconnect with new set
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        s = raw.strip() if isinstance(raw, str) else ""
                        if not s or s[0] not in "[{":
                            continue
                        try:
                            msgs = json.loads(s)
                        except Exception:
                            continue
                        for msg in (msgs if isinstance(msgs, list) else [msgs]):
                            self._handle(msg)
            except Exception as exc:
                log.warning("ws: %s", exc)
                await asyncio.sleep(1.0)

    def _emit_raw(self, msg: dict, et: str, aid: str):
        """v2: verbatim WS event -> mrecev file, tagged with (ws, U/D) and
        arrival time. Event-time truth: no 100ms aliasing, includes the venue
        book `hash` (authoritative-state fingerprint) and tick_size_change."""
        ref = self.tok2m.get(aid)
        row = {"t": round(time.time(), 4), "ev": "WSE", "et": et}
        if ref:
            row["ws"] = ref[0].ws; row["tok"] = ref[1]
        if et == "book":
            # full book events are ~100 levels; keep hash/ts + top-10 per side
            # (SNAP rows carry the 10Hz depth history; WSE preserves EVENT
            # timing + the authoritative hash chain)
            trim = lambda side, rev: sorted(
                [[float(x["price"]), float(x["size"])] for x in msg.get(side, [])],
                key=lambda v: v[0], reverse=rev)[:10]
            row["m"] = {"timestamp": msg.get("timestamp"), "hash": msg.get("hash"),
                        "bids": trim("bids", True), "asks": trim("asks", False)}
        elif et == "price_change":
            # compact: 78-char asset ids dominate the raw payload; encode each
            # change as [tok(U/D/?), side(B/S), px, sz]; keep ts + last hash
            ch = []
            for c in msg.get("changes", []) or msg.get("price_changes", []) or []:
                a2 = c.get("asset_id", aid)
                r2 = self.tok2m.get(a2)
                ch.append([r2[1] if r2 else "?",
                           "B" if c.get("side") == "BUY" else "S",
                           float(c.get("price", 0)), float(c.get("size", 0))])
            row["m"] = {"timestamp": msg.get("timestamp"),
                        "hash": msg.get("hash"), "ch": ch}
        else:
            row["m"] = msg
        self.evq.append(row)
        if len(self.evq) > 50000:       # hard bound; drop oldest under storm
            del self.evq[:10000]

    def _handle(self, msg: dict):
        et = msg.get("event_type"); aid = msg.get("asset_id", "")
        ref = self.tok2m.get(aid)
        now = time.time()
        if et in ("book", "price_change", "tick_size_change", "last_trade_price"):
            self.last_ev_t = now; self.ev_n += 1
            self._emit_raw(msg, et, aid)
        if et == "tick_size_change" and ref:
            ref[0].tick[aid] = str(msg.get("new_tick_size") or msg.get("tick_size") or "")
        if et == "book" and ref:
            m, _ = ref
            m.bids[aid] = {float(b["price"]): float(b["size"]) for b in msg.get("bids", []) if float(b.get("size") or 0) > 0}
            m.asks[aid] = {float(a["price"]): float(a["size"]) for a in msg.get("asks", []) if float(a.get("size") or 0) > 0}
            if msg.get("hash"): m.hash[aid] = msg["hash"]
        elif et == "price_change":
            for ch in msg.get("changes", []) or msg.get("price_changes", []) or []:
                a2 = ch.get("asset_id", aid); r2 = self.tok2m.get(a2)
                if not r2:
                    continue
                m2, _ = r2
                px = float(ch.get("price", 0)); sz = float(ch.get("size", 0))
                book = m2.bids[a2] if ch.get("side") == "BUY" else m2.asks[a2]
                if sz <= 0:
                    book.pop(px, None)
                else:
                    book[px] = sz
                if ch.get("hash"): m2.hash[a2] = ch["hash"]
            if msg.get("hash") and ref: ref[0].hash[aid] = msg["hash"]
        elif et == "last_trade_price" and ref:
            m, ud = ref
            px = float(msg.get("price", 0)); sz = float(msg.get("size", 0))
            m.vol_sh += sz; m.vol_notl += px * sz
            m.trades.append([round(time.time(), 3), ud, px, round(sz, 2), msg.get("side", "")])

    # ── 100ms snapshots: one row PER tracked market ──────────────────────────
    async def snap_loop(self):
        while True:
            try:
                now = time.time()
                cur_ws = grid_window_start(now)
                spot = binance_state.current_price
                cl_t, cl_v = _rtds_latest(rtds_state.point)
                _, tw_v = _rtds_latest(rtds_state.twap)
                for w, m in sorted(self.mkts.items()):
                    role = m.role(now, cur_ws)
                    bo = binance_state.bar_open_at(w) if now >= w else None
                    lead = ((spot - bo) / bo * 1e4) if (bo and spot > 0) else None
                    ub, ubs, ua, uas = m.bbo(m.up)
                    db, dbs, da, das = m.bbo(m.down)
                    ubd, uad = m.depth(m.up)
                    dbd, dad = m.depth(m.down)
                    trd = m.trades[:]; m.trades = []
                    await self.writer.write({
                        "t": round(now, 3), "coin": COIN, "ws": w, "ev": "SNAP",
                        "slug": m.slug, "role": role, "tl": round(m.end - now, 2),
                        "spot": spot, "lead_bps": None if lead is None else round(lead, 2),
                        # ⭐ CHAINLINK settlement stream (added 2026-08-21).
                        # These markets SETTLE on this, not Binance spot, and
                        # the two diverge exactly on near-ties — which is where
                        # the TWAP-recon edge trades. Backtesting the recon on
                        # `lead_bps` is INVALID: the proxy scores the live 5m
                        # vacmaker at -$232 while it actually profits
                        # (ledger #19: 2-3x pessimistic on flip rate).
                        # RTDS is 1Hz, we snap at 10Hz, so cl_ts repeats ~10x —
                        # dedupe on it offline to rebuild the exact 1Hz series
                        # and reconstruct any TWAP window.
                        "cl": cl_v, "cl_ts": cl_t, "tw": tw_v,
                        "ub": ub, "ubs": round(ubs, 1), "ua": ua, "uas": round(uas, 1),
                        "db": db, "dbs": round(dbs, 1), "da": da, "das": round(das, 1),
                        # v2: top-10 depth ladders [px,sz] (ubd desc, uad asc, ...)
                        "ubd": ubd, "uad": uad, "dbd": dbd, "dad": dad,
                        # v2: freshness — age of last WS event, event count, session
                        "evage": round(now - self.last_ev_t, 2) if self.last_ev_t else None,
                        "evn": self.ev_n, "wss": self.ws_sess,
                        "vol": round(m.vol_notl, 2), "volsh": round(m.vol_sh, 1),
                        "trd": trd or None})
            except Exception as exc:
                log.exception("snap: %s", exc)
            await asyncio.sleep(SNAP_SECS)

    async def ev_drain_loop(self):
        """v2: single writer task for the raw event stream (bounded buffer)."""
        while True:
            await asyncio.sleep(0.2)
            if not self.evq:
                continue
            batch, self.evq = self.evq, []
            try:
                for row in batch:
                    await self.evwriter.write(row)
            except Exception as exc:
                log.warning("ev_drain: %s", exc)

    async def binance_loop(self, host: str, streams: list, tag: str):
        """One combined-stream WS per venue; raw payloads, arrival-stamped.

        Reconnects forever with backoff. Deliberately does NOT parse or
        normalise: the point is a faithful tape we can re-derive anything
        from later (lead-lag, liquidity, liquidation cascades)."""
        if not streams:
            return
        url = (host + "/stream?streams="
               + "/".join(f"{BREC_SYMBOL}@{s}" for s in streams))
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(url, ping_interval=20,
                                              ping_timeout=30,
                                              max_size=8 * 1024 * 1024) as ws:
                    log.info("brec %s: subscribed %s@%s", tag, BREC_SYMBOL,
                             ",".join(streams))
                    backoff = 1.0
                    while True:
                        raw = await ws.recv()
                        now = time.time()
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        self.b_msgs += 1
                        self.bq.append({"t": round(now, 4), "ev": tag,
                                        "s": msg.get("stream", ""),
                                        "m": msg.get("data", msg)})
                        if len(self.bq) > 200000:   # hard bound under a storm
                            del self.bq[:50000]
            except Exception as exc:
                log.warning("brec %s: %s", tag, exc)
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    async def b_drain_loop(self):
        """Single writer task for the binance tape (bounded buffer)."""
        if self.bwriter is None:
            return
        last_hb = 0.0
        while True:
            await asyncio.sleep(0.25)
            if self.bq:
                batch, self.bq = self.bq, []
                try:
                    for row in batch:
                        await self.bwriter.write(row)
                except Exception as exc:
                    log.warning("b_drain: %s", exc)
            now = time.time()
            if now - last_hb > 300:
                last_hb = now
                log.info("brec heartbeat  msgs=%d queued=%d", self.b_msgs, len(self.bq))

    async def rest_reconcile_loop(self):
        """v2: periodically pull the venue's authoritative REST book for the
        CURRENT market and record hash + top-3 vs our WS-state hash.
        ⚠️ 2026-09-03: at 30s × 2 tokens × 17 pods (~68 req/min) the CLOB
        REST endpoint rate-limits with 403s (measured: only 30 of ~240
        expected RB rows/hour landed). Now: 150s base + per-coin jitter to
        destagger the fleet, ONE token per cycle (alternating), and
        exponential backoff on 403 up to 20 min. Fleet rate ~7 req/min."""
        import urllib.request as _ur
        base = 150.0
        # deterministic per-coin offset so the 17 pods do not fire together
        off = (sum(ord(c) for c in COIN) % 60)
        backoff = 0.0
        flip = 0
        await asyncio.sleep(off)
        while True:
            await asyncio.sleep(base + backoff)
            try:
                now = time.time()
                cur = self.mkts.get(grid_window_start(now))
                if not cur:
                    continue
                flip ^= 1
                tok, ud = (cur.up, "U") if flip else (cur.down, "D")

                def _fetch(t=tok):
                    req = _ur.Request(
                        f"https://clob.polymarket.com/book?token_id={t}",
                        headers={"User-Agent": "Mozilla/5.0"})
                    return json.loads(_ur.urlopen(req, timeout=8).read())

                d = await asyncio.to_thread(_fetch)
                backoff = 0.0
                rh = d.get("hash") or ""
                wh = cur.hash.get(tok) or ""
                top = lambda side, rev: sorted(
                    [[float(x["price"]), float(x["size"])] for x in d.get(side, [])],
                    key=lambda v: v[0], reverse=rev)[:3]
                await self.writer.write({
                    "t": round(now, 3), "coin": COIN, "ws": cur.ws, "ev": "RB",
                    "tok": ud, "rh": rh, "wh": wh, "match": bool(rh) and rh == wh,
                    "rb3": top("bids", True), "ra3": top("asks", False),
                    "tick": cur.tick.get(tok)})
            except Exception as exc:
                if "403" in str(exc) or "429" in str(exc):
                    backoff = min(1200.0, backoff * 2 + 60.0)
                    log.warning("rest_reconcile throttled (%s); backoff=%.0fs",
                                exc, backoff)
                else:
                    log.warning("rest_reconcile: %s", exc)

    async def run(self):
        log.info("multi_recorder v2 coin=%s ahead=%d snap=%.0fms (ev-stream+hash+depth+freshness)",
                 COIN, AHEAD, SNAP_SECS * 1000)
        if BREC_SPOT or BREC_FUT:
            log.info("brec ON sym=%s spot=%s fut=%s", BREC_SYMBOL,
                     ",".join(BREC_SPOT) or "-", ",".join(BREC_FUT) or "-")
        _seed_history()
        await asyncio.gather(run_binance_ws(), run_rtds(RTDS_TOPICS),
                             self.discover_loop(),
                             self.resolve_loop(), self.ws_loop(), self.snap_loop(),
                             self.ev_drain_loop(), self.rest_reconcile_loop(),
                             self.binance_loop(BREC_SPOT_HOST, BREC_SPOT, "BIN"),
                             self.binance_loop(BREC_FUT_HOST, BREC_FUT, "BINF"),
                             self.b_drain_loop())


def main():
    asyncio.run(MultiRecorder().run())


if __name__ == "__main__":
    main()
