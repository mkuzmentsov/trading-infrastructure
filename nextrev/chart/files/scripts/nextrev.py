"""nextrev — next-bar reversal bettor (ldjfgkl archetype, stricter pricing).

Archetype (leaderboard #1, 0x79248fc6…b32, +$10k/5h): when the CURRENT bar has a
strong directional move, buy the NEXT bar's OPPOSITE side ~30s before it opens,
hold to resolution. He pays 0.53-0.55; measured raw reversal odds are only ~54%
(≈0 EV at his price) — so WE only enter at <= NEXTREV_CAP (0.50): same signal,
strictly better price, ~54% win at <=0.50 = the only version our data supports.

Per current bar:
  - ARM at t_left <= ARM_SECS (45): prefetch the NEXT market (pm_ws cache),
    presign BUYs for BOTH its tokens at CAP (2-CPU pod → both signs ~instant).
  - FIRE window t_left in [FIRE_LO, FIRE_HI] (5..35s): if |lead| >= MIN_LEAD_BPS
    (20), buy the next bar's REVERSAL side (lead>0 → next DOWN) with a FAK at
    <= CAP. One bet per next-bar. Hold to gamma resolution.
  - Daily realized loss <= MAX_DAILY_LOSS (20) → halt.

Minimal logging: NEXTREV_ARM / NEXTREV_BET / NEXTREV_SETTLE / NEXTREV_HALT only.
Env: NEXTREV_CAP NEXTREV_MIN_LEAD_BPS NEXTREV_ARM_SECS NEXTREV_FIRE_LO/HI
     NEXTREV_NOTIONAL NEXTREV_MAX_DAILY_LOSS.
"""
from __future__ import annotations

import asyncio
import math
import os
import time

from config import DRY_RUN, TRAINING_EVENT_LOG_PATH, log
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

CAP = float(os.getenv("NEXTREV_CAP", "0.50"))
MIN_LEAD_BPS = float(os.getenv("NEXTREV_MIN_LEAD_BPS", "20"))
ARM_SECS = float(os.getenv("NEXTREV_ARM_SECS", "45"))
FIRE_LO = float(os.getenv("NEXTREV_FIRE_LO", "5"))
FIRE_HI = float(os.getenv("NEXTREV_FIRE_HI", "35"))
NOTIONAL = float(os.getenv("NEXTREV_NOTIONAL", "5"))
MAX_DAILY_LOSS = float(os.getenv("NEXTREV_MAX_DAILY_LOSS", "20"))
# price = min(next-bar best ask - 1 tick, MAX_PX): rests just under the ask as a
# MAKER limit (never crosses; no taker fee; fills easiest in queue). MAX_PX guards
# EV: at ~54% reversal odds, 0.52 keeps ~2pts; ldjfgkl's 0.53-0.55 is ~0 EV.
MAX_PX = float(os.getenv("NEXTREV_MAX_PX", "0.52"))
MIN_PX = 0.40

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _shares() -> float:
    return max(5.0, math.floor(NOTIONAL / max(CAP, 0.01)))


def outcome_up(ws: int):
    """Gamma (Chainlink) resolution: True=UP won, False=DOWN, None=unresolved."""
    import json, urllib.request
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


class NextRevStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.armed: dict[int, dict] = {}     # next_ws -> {"up":tok,"down":tok}
        self.acted: set[int] = set()         # next_ws bets placed
        self.settled: set[int] = set()
        self.open_bets: dict[int, dict] = {}
        self.pending: dict[int, dict] = {}   # next_ws -> resting GTC awaiting finalize
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self._arming = False

    def bind(self, runner) -> None:
        self.runner = runner
        _event("NEXTREV_START", live=_real, cap=CAP, min_lead_bps=MIN_LEAD_BPS,
               arm=ARM_SECS, fire=[FIRE_LO, FIRE_HI], notional=NOTIONAL,
               max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        return []                            # we presign the NEXT bar ourselves

    async def _arm_next(self, cur_end: int) -> None:
        """Prefetch next market + presign both tokens at CAP (off hot path)."""
        if self._arming or cur_end in self.armed:
            return
        self._arming = True
        try:
            from core.gamma import get_up_down_tokens
            from core.pm_ws import _prefetched_market, prefetch_next_market
            ok = await asyncio.to_thread(prefetch_next_market)
            mk = _prefetched_market.get("market") if ok else None
            if not mk or _prefetched_market.get("start_ts") != cur_end:
                return
            up, down = get_up_down_tokens(mk)
            if not up or not down:
                return
            toks = {"up": up["token_id"], "down": down["token_id"]}
            sz = _shares()
            await self.runner.exec.presign_buy(f"nr-{cur_end}-UP", toks["up"], CAP, sz)
            await self.runner.exec.presign_buy(f"nr-{cur_end}-DOWN", toks["down"], CAP, sz)
            self.armed[cur_end] = toks
            _event("NEXTREV_ARM", next_bar=cur_end)
        except Exception as exc:
            log.warning("arm failed: %s", exc)
        finally:
            self._arming = False

    async def _finalize(self, ws: int) -> None:
        p = self.pending.pop(ws, None)
        if not p:
            return
        filled = p["imm_fill"]; oid = p["oid"]
        if oid:
            pf = await self.runner.exec.poll_filled(oid)
            if pf is not None:
                filled = max(filled, pf)
            await self.runner.exec.cancel(oid)
        if filled and filled > 0:
            rested = max(0.0, filled - p["imm_fill"])
            cost = p["imm_fill"] * p["imm_px"] + rested * p.get("px", CAP)
            px = cost / filled
            self.open_bets[ws] = {"side": p["side"], "fill_px": px, "fill_qty": filled}
            _event("NEXTREV_FILL", bar=ws, side=p["side"], filled=round(filled, 1),
                   fill_px=round(px, 4), rested=round(rested, 1), live=_real)
        else:
            _event("NEXTREV_NOFILL", bar=ws, side=p["side"], order=oid or "FAIL")

    async def on_tick(self, ctx) -> None:
        if self.halted:
            return
        # finalize any resting order whose bar has now OPENED (bet bar == current)
        if ctx.ws in self.pending:
            asyncio.create_task(self._finalize(ctx.ws))
        tl = ctx.t_left
        next_ws = ctx.ws + 300               # the bar we bet on
        # ARM: prefetch + presign next-bar tokens
        if tl <= ARM_SECS and next_ws not in self.armed and not self._arming:
            asyncio.create_task(self._arm_next(next_ws))
        # FIRE
        if next_ws in self.acted or next_ws not in self.armed:
            return
        if not (FIRE_LO <= tl <= FIRE_HI):
            return
        if ctx.bar_open is None or ctx.spot <= 0 or ctx.spot_age > 5.0:
            return
        lead_bps = (ctx.spot - ctx.bar_open) / ctx.bar_open * 1e4
        if abs(lead_bps) < MIN_LEAD_BPS:
            return
        rev = "DOWN" if lead_bps > 0 else "UP"   # bet the bounce
        self.acted.add(next_ws)
        toks = self.armed[next_ws]
        token = toks["up"] if rev == "UP" else toks["down"]
        t0 = time.time()
        # price just UNDER the next-bar best ask (stay a resting maker limit)
        px = CAP
        try:
            ob = await asyncio.to_thread(self.runner.exec.clob.get_order_book, token)
            asks = [float(getattr(a, "price", a.get("price") if isinstance(a, dict) else 1))
                    for a in (getattr(ob, "asks", None) or [])]
            if asks:
                px = round(min(MAX_PX, max(MIN_PX, min(asks) - 0.01)), 2)
        except Exception:
            pass
        key = f"nr-{next_ws}-{rev}"
        try:
            if px == CAP and self.runner.exec.has_presigned(key):
                oid, matched, post_ms, avg_px, fq = await self.runner.exec.fire_presigned(key)
            else:
                oid, matched, _s, post_ms, avg_px, fq = await self.runner.exec.fire_direct(
                    token, px, _shares())
        except Exception as exc:
            _event("NEXTREV_BET", next_bar=next_ws, side=rev, err=str(exc)[:120])
            return
        px = avg_px if avg_px else CAP
        if not _real and fq is None:
            fq = _shares()                   # paper: assume fill at cap
        # GTC: order RESTS on the next-bar pre-open book; finalize at bar open
        self.pending[next_ws] = {"oid": oid, "side": rev, "px": px,
                                 "imm_fill": fq or 0.0, "imm_px": avg_px if avg_px else px}
        _event("NEXTREV_BET", next_bar=next_ws, side=rev, lead_bps=round(lead_bps, 1),
               t_left=round(tl, 1), fill_px=round(px, 4),
               fill_qty=None if fq is None else round(fq, 1),
               ms=round((time.time() - t0) * 1000, 1), order=oid or "FAIL",
               matched=matched, live=_real)

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            for ws in [w for w in self.open_bets if w + 300 < now - 8
                       and w not in self.settled]:
                bet = self.open_bets[ws]
                oc = await asyncio.to_thread(outcome_up, ws)
                if oc is None:
                    if now - (ws + 300) > 600:
                        self.settled.add(ws)
                    continue
                won = (bet["side"] == "UP") == oc
                q = bet["fill_qty"]
                pnl = q * ((1.0 if won else 0.0) - bet["fill_px"])
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.settled.add(ws)
                _event("NEXTREV_SETTLE", bar=ws, side=bet["side"],
                       outcome="UP" if oc else "DOWN", won=won,
                       fill_px=round(bet["fill_px"], 4), qty=round(q, 1),
                       pnl=round(pnl, 3), day_pnl=round(self.day_pnl[day], 2),
                       live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("NEXTREV_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))


def main():
    from execution.runner import TakerRunner
    log.info("nextrev %s: coin=%s cap=%.2f lead>=%.0fbps fire[%g,%g] $%.0f/bet dd=$%.0f",
             "LIVE" if _real else "PAPER", COIN, CAP, MIN_LEAD_BPS, FIRE_LO, FIRE_HI,
             NOTIONAL, MAX_DAILY_LOSS)
    runner = TakerRunner(NextRevStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
