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
from core.gamma import (fetch_market_for_window, get_up_down_tokens,
                        grid_window_start, next_window_start, window_slug)
from ws_recorder import RotatingWriter, _seed_history

AHEAD = int(os.getenv("MREC_AHEAD", "3"))
SNAP_SECS = max(20, int(float(os.getenv("SNAPSHOT_MS", "100")))) / 1000.0
# distinguish archives by bar length: btc-mrec (5m), btc-mrec1h, btc-mrec1d
_SUFFIX = {3600: "1h", 86400: "1d"}.get(BAR_SECONDS, "")


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
        self.trades: list = []          # unemitted prints
        self.resolved: str | None = None
        self.res_poll_at = 0.0

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
                # safety: give up 10min after close
                if now - m.end > 600 and w in self.mkts:
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

    def _handle(self, msg: dict):
        et = msg.get("event_type"); aid = msg.get("asset_id", "")
        ref = self.tok2m.get(aid)
        if et == "book" and ref:
            m, _ = ref
            m.bids[aid] = {float(b["price"]): float(b["size"]) for b in msg.get("bids", []) if float(b.get("size") or 0) > 0}
            m.asks[aid] = {float(a["price"]): float(a["size"]) for a in msg.get("asks", []) if float(a.get("size") or 0) > 0}
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
                for w, m in sorted(self.mkts.items()):
                    role = m.role(now, cur_ws)
                    bo = binance_state.bar_open_at(w) if now >= w else None
                    lead = ((spot - bo) / bo * 1e4) if (bo and spot > 0) else None
                    ub, ubs, ua, uas = m.bbo(m.up)
                    db, dbs, da, das = m.bbo(m.down)
                    trd = m.trades[:]; m.trades = []
                    await self.writer.write({
                        "t": round(now, 3), "coin": COIN, "ws": w, "ev": "SNAP",
                        "slug": m.slug, "role": role, "tl": round(m.end - now, 2),
                        "spot": spot, "lead_bps": None if lead is None else round(lead, 2),
                        "ub": ub, "ubs": round(ubs, 1), "ua": ua, "uas": round(uas, 1),
                        "db": db, "dbs": round(dbs, 1), "da": da, "das": round(das, 1),
                        "vol": round(m.vol_notl, 2), "volsh": round(m.vol_sh, 1),
                        "trd": trd or None})
            except Exception as exc:
                log.exception("snap: %s", exc)
            await asyncio.sleep(SNAP_SECS)

    async def run(self):
        log.info("multi_recorder coin=%s ahead=%d snap=%.0fms", COIN, AHEAD, SNAP_SECS * 1000)
        _seed_history()
        await asyncio.gather(run_binance_ws(), self.discover_loop(),
                             self.resolve_loop(), self.ws_loop(), self.snap_loop())


def main():
    asyncio.run(MultiRecorder().run())


if __name__ == "__main__":
    main()
