"""openlag.py — pre-open locked-strike taker PROBE (strat-openlag.md).

The next bar's strike is the Chainlink TWAP over [ws-62, ws-3]: locked 3s
before the bar opens and nowcastable from ~ws-62 onward. When the latest
Chainlink price is displaced from the forming strike by z = disp/sigma5m >=
OL_Z_MIN, buy that side of the NEXT bar's market pre-open with one small FAK.

PROBE STATUS (2026-08-29, user-approved): offline the current market prices
this at the ws-3 book (-2..-3c/sh at |z|>=1.2); the ws-10 fire retains
+2.7..+4.1c/sh (p=0.02) which any fill haircut may erase. This bot's product
is DATA, not income: (a) the live pre-open FAK match rate — unmeasurable
offline; (b) a running detector for the seam re-opening (it demonstrably
existed 08-07..17 at +14c/sh). Every bar emits OL_EVAL regardless of gate.

Env knobs (all OL_*): OL_Z_MIN(1.2) OL_FIRE_START(10) OL_FIRE_END(3)
OL_CLIP_USD(5) OL_MAX_ASK(0.72) OL_MIN_ASK(0.30) OL_MIN_TICKS(35)
OL_MIN_SIGMA_BPS(1.0) OL_MAX_TICK_AGE(8) OL_ATTEMPTS(2).
Risk: LIVE_MAX_ORDER_USD caps the clip, LIVE_MAX_DAILY_LOSS_USD (default 7)
is a sticky per-UTC-day halt persisted to /app/logs/openlag_halt.json.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
import urllib.request

from config import (COIN, DRY_RUN, LIVE_MAX_DAILY_LOSS_USD, LIVE_MAX_ORDER_USD,
                    POLYMARKET_RTDS_SYMBOL, TRAINING_EVENT_LOG_PATH, log)
from core.gamma import (fetch_market_for_window, get_up_down_tokens,
                        grid_window_start, next_window_start)
from core.rtds import rtds_state, run_rtds
from execution.events import EventLog

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

Z_MIN = float(os.getenv("OL_Z_MIN", "1.2"))
FIRE_START = float(os.getenv("OL_FIRE_START", "10"))   # secs before next open
FIRE_END = float(os.getenv("OL_FIRE_END", "3"))
CLIP_USD = min(float(os.getenv("OL_CLIP_USD", "5")), LIVE_MAX_ORDER_USD)
MAX_ASK = float(os.getenv("OL_MAX_ASK", "0.72"))
MIN_ASK = float(os.getenv("OL_MIN_ASK", "0.30"))
MIN_TICKS = int(os.getenv("OL_MIN_TICKS", "35"))
MIN_SIGMA = float(os.getenv("OL_MIN_SIGMA_BPS", "1.0"))
MAX_TICK_AGE = float(os.getenv("OL_MAX_TICK_AGE", "8"))
ATTEMPTS = int(os.getenv("OL_ATTEMPTS", "2"))
MAX_DD = LIVE_MAX_DAILY_LOSS_USD
HALT_FILE = os.path.join(os.path.dirname(TRAINING_EVENT_LOG_PATH) or "/tmp",
                         "openlag_halt.json")
SYM = POLYMARKET_RTDS_SYMBOL

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _utc_day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


# ── sigma5m from Binance 5m klines (vol scale only, not the signal) ─────────
_sigma_cache: tuple[float, float | None] = (0.0, None)


def _sigma5m_bps() -> float | None:
    global _sigma_cache
    now = time.time()
    if now - _sigma_cache[0] < 240:
        return _sigma_cache[1]
    try:
        url = (f"https://api.binance.com/api/v3/klines?symbol="
               f"{COIN.upper()}USDT&interval=5m&limit=14")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        rows = json.loads(urllib.request.urlopen(req, timeout=10).read())
        closes = [float(r[4]) for r in rows[:-1]]  # drop the open bar
        rets = [math.log(closes[i] / closes[i - 1]) * 1e4
                for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(rets) >= 8:
            mu = sum(rets) / len(rets)
            sig = (sum((x - mu) ** 2 for x in rets) / len(rets)) ** 0.5
            _sigma_cache = (now, sig)
            return sig
    except Exception as exc:
        log.warning("openlag sigma fetch failed: %s", exc)
    _sigma_cache = (now, _sigma_cache[1])
    return _sigma_cache[1]


def _best_ask(token_id: str) -> tuple[float | None, float]:
    """(best_ask, size) from the CLOB REST book; None when book empty."""
    try:
        url = f"https://clob.polymarket.com/book?token_id={token_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=5).read())
        asks = d.get("asks") or []
        if not asks:
            return None, 0.0
        best = min(asks, key=lambda a: float(a["price"]))
        return float(best["price"]), float(best["size"])
    except Exception as exc:
        log.warning("openlag book read failed: %s", exc)
        return None, 0.0


def outcome_up(ws: int):
    """Gamma resolution for the bar starting at ws (True/False/None)."""
    from core.gamma import window_slug
    try:
        url = ("https://gamma-api.polymarket.com/markets?slug=" + window_slug(ws)
               + "&closed=true")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


class Openlag:
    def __init__(self) -> None:
        self.clob = None
        self.strikes: list[tuple[int, float]] = []   # (ws, strike) per bar
        self.next_ws = 0
        self.tokens: dict | None = None      # {"up":id,"down":id,"cid":...}
        self.fired: set[int] = set()
        self.evaled: set[int] = set()
        self.attempts: dict[int, int] = {}
        self.bets: list[dict] = []
        self.day_pnl: dict[str, float] = {}
        self.halted_day = ""
        self._load_halt()

    # ── sticky halt ──────────────────────────────────────────────────────
    def _load_halt(self) -> None:
        try:
            with open(HALT_FILE) as f:
                d = json.load(f)
            if d.get("day") == _utc_day():
                self.halted_day = d["day"]
                self.day_pnl[d["day"]] = float(d.get("pnl", 0.0))
                log.warning("openlag: sticky halt restored for %s (pnl %.2f)",
                            d["day"], self.day_pnl[d["day"]])
        except Exception:
            pass

    def _save_halt(self, day: str) -> None:
        try:
            with open(HALT_FILE, "w") as f:
                json.dump({"day": day, "pnl": self.day_pnl.get(day, 0.0)}, f)
        except Exception as exc:
            log.error("openlag: halt persist failed: %s", exc)

    def _halted(self) -> bool:
        return self.halted_day == _utc_day()

    # ── market discovery for the NEXT bar ────────────────────────────────
    async def discover_loop(self) -> None:
        while True:
            try:
                now = time.time()
                nxt = next_window_start(grid_window_start(now))
                if nxt != self.next_ws:
                    tl_next = nxt - now  # secs until next open (300..0)
                    if tl_next <= 60:
                        mkt = await asyncio.to_thread(fetch_market_for_window, nxt)
                        if mkt:
                            up, down = get_up_down_tokens(mkt)
                            if up and down:
                                self.next_ws = nxt
                                self.tokens = {
                                    "up": str(up["token_id"]),
                                    "down": str(down["token_id"]),
                                    "cid": mkt.get("conditionId") or "",
                                }
                                _event("OL_DISCOVER", bar=nxt,
                                       slug=mkt.get("slug"), ok=True)
            except Exception as exc:
                log.error("openlag discover: %s", exc)
            await asyncio.sleep(2.0)

    # ── signal ───────────────────────────────────────────────────────────
    def _sigma_fallback(self) -> float | None:
        """sigma5m from own strike history (hype has no Binance spot; also
        covers Binance outages). Needs >=9 consecutive strikes (~45 min)."""
        h = self.strikes[-13:]
        rets = [math.log(h[i][1] / h[i - 1][1]) * 1e4 for i in range(1, len(h))
                if h[i][0] - h[i - 1][0] == 300 and h[i - 1][1] > 0]
        if len(rets) < 8:
            return None
        mu = sum(rets) / len(rets)
        return (sum((x - mu) ** 2 for x in rets) / len(rets)) ** 0.5

    def _signal(self, nxt: int):
        wm = rtds_state.window_mean(SYM, nxt - 62, nxt - 3)
        if not wm:
            return None, "no_strike", {}
        strike, obs, total = wm
        if not self.strikes or self.strikes[-1][0] != nxt:
            self.strikes.append((nxt, strike))
            del self.strikes[:-20]
        latest = rtds_state.latest(SYM)
        if not latest:
            return None, "no_tick", {}
        tick_ts, cl = latest
        age = time.time() - tick_ts
        sig = _sigma5m_bps()
        src_sig = "binance"
        if not sig:
            sig = self._sigma_fallback()
            src_sig = "strikes"
        info = {"strike": round(strike, 6), "obs": obs, "cl": cl,
                "tick_age": round(age, 1),
                "sigma": round(sig, 2) if sig else None, "sig_src": src_sig}
        if obs < MIN_TICKS:
            return None, "few_ticks", info
        if age > MAX_TICK_AGE:
            return None, "stale_tick", info
        if not sig or sig < MIN_SIGMA:
            return None, "no_sigma", info
        m = (cl / strike - 1) * 1e4
        z = m / sig
        info.update({"m_bps": round(m, 2), "z": round(z, 2)})
        return z, "ok", info

    # ── fire loop ────────────────────────────────────────────────────────
    async def fire_loop(self) -> None:
        while True:
            await asyncio.sleep(0.3)
            try:
                now = time.time()
                nxt = self.next_ws
                if nxt <= 0 or self.tokens is None or nxt in self.fired:
                    continue
                tl_next = nxt - now
                if not (FIRE_END <= tl_next <= FIRE_START):
                    continue
                z, status, info = self._signal(nxt)
                if nxt not in self.evaled:
                    self.evaled.add(nxt)
                    _event("OL_EVAL", bar=nxt, status=status,
                           tl_next=round(tl_next, 2), **info)
                if z is None:
                    continue
                if abs(z) < Z_MIN:
                    continue
                if self.attempts.get(nxt, 0) >= ATTEMPTS:
                    continue
                if self._halted():
                    _event("OL_SKIP", bar=nxt, reason="halt", **info)
                    self.fired.add(nxt)
                    continue
                side = "UP" if z > 0 else "DOWN"
                token = self.tokens["up"] if side == "UP" else self.tokens["down"]
                ask, ask_sz = await asyncio.to_thread(_best_ask, token)
                if ask is None:
                    _event("OL_SKIP", bar=nxt, reason="no_ask", side=side, **info)
                    self.attempts[nxt] = self.attempts.get(nxt, 0) + 1
                    continue
                if ask > MAX_ASK or ask < MIN_ASK:
                    _event("OL_SKIP", bar=nxt, reason="ask_band", side=side,
                           ask=ask, ask_sz=ask_sz, **info)
                    self.fired.add(nxt)
                    continue
                shares = max(5.0, math.floor(CLIP_USD / ask))
                self.attempts[nxt] = self.attempts.get(nxt, 0) + 1
                _event("OL_TRIGGER", bar=nxt, side=side, ask=ask, ask_sz=ask_sz,
                       shares=shares, attempt=self.attempts[nxt],
                       tl_next=round(tl_next, 2), live=_real, **info)
                if not _real:
                    self.fired.add(nxt)
                    continue
                from engine.clob import place_market_buy
                oid, matched, avg_px, qty = await asyncio.to_thread(
                    place_market_buy, self.clob, token, shares, ask)
                _event("OL_ORDER", bar=nxt, side=side, order=oid,
                       matched=bool(matched), px=avg_px, qty=qty, ask_seen=ask,
                       attempt=self.attempts[nxt])
                if matched and avg_px and qty:
                    self.fired.add(nxt)
                    self.bets.append({"bar": nxt, "side": side, "px": avg_px,
                                      "qty": qty, "settled": False})
                # not matched -> another attempt allowed while in-window
            except Exception as exc:
                log.error("openlag fire: %s", exc)

    # ── settle loop ──────────────────────────────────────────────────────
    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(20.0)
            try:
                now = time.time()
                for bet in self.bets:
                    if bet["settled"] or now < bet["bar"] + 330:
                        continue
                    oc = await asyncio.to_thread(outcome_up, bet["bar"])
                    if oc is None:
                        if now - bet["bar"] > 1500:
                            bet["settled"] = True
                            _event("OL_SETTLE_TIMEOUT", bar=bet["bar"])
                        continue
                    won = (bet["side"] == "UP") == oc
                    pnl = bet["qty"] * ((1.0 if won else 0.0) - bet["px"])
                    day = _utc_day()
                    self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                    bet["settled"] = True
                    _event("OL_SETTLE", bar=bet["bar"], side=bet["side"],
                           outcome="UP" if oc else "DOWN", won=won,
                           px=round(bet["px"], 4), qty=round(bet["qty"], 1),
                           pnl=round(pnl, 3),
                           day_pnl=round(self.day_pnl[day], 2))
                    if self.day_pnl[day] <= -MAX_DD and self.halted_day != day:
                        self.halted_day = day
                        self._save_halt(day)
                        _event("OL_HALT", day=day,
                               day_pnl=round(self.day_pnl[day], 2), max_dd=MAX_DD)
            except Exception as exc:
                log.error("openlag settle: %s", exc)

    async def run(self) -> None:
        if _real:
            from engine.clob import build_clob_client
            self.clob = build_clob_client()
        _event("OL_START", live=_real, z_min=Z_MIN, fire=[FIRE_START, FIRE_END],
               clip=CLIP_USD, max_ask=MAX_ASK, min_ask=MIN_ASK,
               min_ticks=MIN_TICKS, max_dd=MAX_DD, sym=SYM)
        log.info("openlag %s: coin=%s z>=%.2f fire[ws-%g,ws-%g] $%.0f ask[%.2f,%.2f] dd$%.0f",
                 "LIVE" if _real else "DRY", COIN, Z_MIN, FIRE_START, FIRE_END,
                 CLIP_USD, MIN_ASK, MAX_ASK, MAX_DD)
        await asyncio.gather(
            run_rtds(topics=("crypto_prices_chainlink",)),
            self.discover_loop(),
            self.fire_loop(),
            self.settle_loop(),
        )


def main():
    asyncio.run(Openlag().run())


if __name__ == "__main__":
    main()
