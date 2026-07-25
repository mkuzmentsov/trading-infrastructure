"""flipbet.py — CONTRARIAN near-tie flip bet on UpDown 5m markets.

Hypothesis (user, 2026-07-24): on a bar where BINANCE shows only a near-tie
(outcome NOT decided by Binance) but the MARKET has already pushed the trailing
side cheap (≤2c), the market is over-confident vs Binance. Since the settlement is
Chainlink (a different aggregate that flips ~near-ties), buying that cheap
"losing" side at 1-2c and holding to resolution should flip to $1 more often than
its 2c price implies → +EV. (My aggregate test said cheap post-close buys win ~1%;
this bot isolates the market-cheap-AND-Binance-near-tie condition to measure THAT
subset directly. PAPER until it proves +EV.)

Per bar:
  - lead = (spot-open)/open; lose_side = DOWN if lead>0 else UP (the trailing side).
  - GATES (bet the lose_side only if ALL hold):
      * timing tl in [TL_LO, TL_HI]  (late bar through just past close)
      * FLIP_MIN_LEAD_BPS <= |lead_bps| <= FLIP_MAX_LEAD_BPS
        (a defined trailing side, but NOT a decisive/100%-sure Binance move —
         "price not too far from open")
      * lose_side ASK <= FLIP_CAP with size  (market already made it cheap)
  - buy $FLIP_NOTIONAL of lose_side at the cap (FAK), hold to Chainlink resolution.
  - one bet per bar; daily realized loss <= FLIP_MAX_DAILY_LOSS -> halt.

Env: FLIP_CAP(0.02) FLIP_TL_LO(-3) FLIP_TL_HI(60) FLIP_MIN_LEAD_BPS(1)
     FLIP_MAX_LEAD_BPS(15) FLIP_NOTIONAL(1) FLIP_MAX_DAILY_LOSS(20). Reuses the
     TakerRunner harness + FastExec; FAV_ORDER_TYPE=fak (take the cheap ask).
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

CAP = float(os.getenv("FLIP_CAP", "0.02"))
TL_LO = float(os.getenv("FLIP_TL_LO", "-3"))          # up to 3s past close
TL_HI = float(os.getenv("FLIP_TL_HI", "60"))          # from 60s before close
MIN_LEAD_BPS = float(os.getenv("FLIP_MIN_LEAD_BPS", "1"))
MAX_LEAD_BPS = float(os.getenv("FLIP_MAX_LEAD_BPS", "15"))
NOTIONAL = float(os.getenv("FLIP_NOTIONAL", "1"))
MAX_DAILY_LOSS = float(os.getenv("FLIP_MAX_DAILY_LOSS", "20"))

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


class FlipStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.acted: set[int] = set()
        self.settled: set[int] = set()
        self.open_bets: dict[int, dict] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False

    def bind(self, runner) -> None:
        self.runner = runner
        _event("FLIP_START", live=_real, cap=CAP, tl=[TL_LO, TL_HI],
               lead_band=[MIN_LEAD_BPS, MAX_LEAD_BPS], notional=NOTIONAL,
               max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        sz = _shares()
        reqs = []
        if ctx.up_token:
            reqs.append(("flip-UP", ctx.up_token, CAP, sz))
        if ctx.down_token:
            reqs.append(("flip-DOWN", ctx.down_token, CAP, sz))
        return reqs

    async def on_tick(self, ctx) -> None:
        ws = ctx.ws
        if self.halted or ws in self.acted or ws in self.settled:
            return
        if ctx.bar_open is None or ctx.spot <= 0 or ctx.spot_age > 5.0:
            return
        tl = ctx.t_left
        if not (TL_LO <= tl <= TL_HI):
            return
        lead = (ctx.spot - ctx.bar_open) / ctx.bar_open
        lead_bps = lead * 1e4
        # need a defined trailing side, but NOT a decisive (100%-sure) Binance move
        if not (MIN_LEAD_BPS <= abs(lead_bps) <= MAX_LEAD_BPS):
            return
        lose_side = "DOWN" if lead > 0 else "UP"          # side Binance has trailing
        ask = ctx.down_ask if lose_side == "DOWN" else ctx.up_ask
        asz = ctx.down_ask_size if lose_side == "DOWN" else ctx.up_ask_size
        if ask is None or ask > CAP or not asz or asz <= 0:
            return                                        # market must have it cheap (<=CAP)
        # FIRE — buy the cheap trailing side, bet Chainlink flips it
        self.acted.add(ws)
        token = ctx.up_token if lose_side == "UP" else ctx.down_token
        key = f"flip-{lose_side}"
        t0 = time.time()
        try:
            if self.runner.exec.has_presigned(key):
                oid, matched, post_ms, avg_px, fill_qty = \
                    await self.runner.exec.fire_presigned(key)
            else:
                oid, matched, _s, post_ms, avg_px, fill_qty = \
                    await self.runner.exec.fire_direct(token, CAP, _shares())
        except Exception as exc:
            _event("FLIP_ERR", bar=ws, side=lose_side, err=str(exc)[:160])
            return
        fill_px = avg_px if avg_px else ask
        if not _real and fill_qty is None:                # paper: fill min(want, top size)
            fill_qty = min(_shares(), asz)
        self.open_bets[ws] = {"side": lose_side, "fill_px": fill_px,
                              "fill_qty": fill_qty, "order_id": oid}
        _event("FLIP_BET", bar=ws, side=lose_side, lead_bps=round(lead_bps, 1),
               t_left=round(tl, 1), ask=round(ask, 4), ask_size=round(asz, 1),
               fill_px=round(fill_px, 4),
               fill_qty=None if fill_qty is None else round(fill_qty, 1),
               decide_ms=round((time.time() - t0) * 1000, 1),
               order=oid or "FAILED", matched=matched, live=_real)

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
                        _event("FLIP_SETTLE_TIMEOUT", bar=ws)
                    continue
                won = (bet["side"] == "UP") == oc          # our bet side won?
                q = bet["fill_qty"] or 0.0
                pnl = q * ((1.0 if won else 0.0) - bet["fill_px"])
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.settled.add(ws)
                _event("FLIP_SETTLE", bar=ws, side=bet["side"],
                       outcome="UP" if oc else "DOWN", flipped=won,
                       fill_px=round(bet["fill_px"], 4), qty=round(q, 1),
                       pnl=round(pnl, 3), day_pnl=round(self.day_pnl[day], 2),
                       live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("FLIP_HALT", day=day, day_pnl=round(self.day_pnl[day], 2),
                           max_dd=MAX_DAILY_LOSS)


def main():
    from execution.runner import TakerRunner
    log.info("flipbet %s: coin=%s cap=%.2f lead[%.0f,%.0f]bps tl[%.0f,%.0f] $%.0f/bet maxDD=$%.0f",
             "LIVE" if _real else "PAPER", COIN, CAP, MIN_LEAD_BPS, MAX_LEAD_BPS,
             TL_LO, TL_HI, NOTIONAL, MAX_DAILY_LOSS)
    runner = TakerRunner(FlipStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
