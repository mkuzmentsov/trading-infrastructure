"""pairarb.py — complementary-pair arbitrage on 5m up/down bars.

MECHANISM. UP and DOWN of the same bar are complementary: exactly one settles
at $1.00. So whenever

    ask_UP + ask_DOWN + fees < $1.00

buying one share of each pays $1.00 for less than $1.00 — regardless of which
side wins. No prediction, no Binance feed, no directional exposure. It is the
only edge we have found that the taker fee does not eat, because the profit is
structural rather than a shading of probability.

WHY IT IS RISKLESS ONLY IF EXECUTED CAREFULLY. The danger is LEG RISK: filling
one side and not the other leaves a naked coin flip. Two rules remove it:
  1. size BOTH legs to min(our size, depth_UP, depth_DOWN) — never take more on
     one side than the other, or depth asymmetry manufactures a naked position;
  2. fire both as FAK and, if one leg comes back short, immediately unwind the
     excess at the bid rather than carry it to resolution.

Backtest (mrec, 4 days, 6 coins, 50sh, 200ms latency, 0.5c min edge, fees
charged both legs): ~$13.55/day with ZERO legged positions, because the
arrival-edge recheck simply declines to trade once the crossing has closed.
Latency dominates everything: at 0ms doge alone is worth $36/day, at 200ms it
is $0.89 — its crossings last a median 0.71s. bnb (median 2.29s) survives.

Env:
  PA_MIN_EDGE      minimum net edge per share after fees (default 0.005)
  PA_NOTIONAL      USD per pair leg (default 25)
  PA_COOLDOWN      seconds between fires on one bar (default 30)
  PA_MAX_DAILY_LOSS halt after this much loss (default 20)
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

MIN_EDGE = float(os.getenv("PA_MIN_EDGE", "0.005"))
NOTIONAL = float(os.getenv("PA_NOTIONAL", "25"))
COOLDOWN = float(os.getenv("PA_COOLDOWN", "30"))
MAX_DAILY_LOSS = float(os.getenv("PA_MAX_DAILY_LOSS", "20"))
FEE_RATE = 0.07

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def fee(p: float) -> float:
    return FEE_RATE * p * (1.0 - p)


class PairArbStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.halted = False
        self.day_pnl: dict[str, float] = {}
        self._last_fire: dict[int, float] = {}
        self._done: set[int] = set()

    def bind(self, runner) -> None:
        self.runner = runner
        _event("PA_START", live=_real, min_edge=MIN_EDGE, notional=NOTIONAL,
               max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        return []          # prices are unknown until a crossing appears

    async def on_tick(self, ctx) -> None:
        if self.halted:
            return
        ws = ctx.ws
        from core.pm_ws import pm_state
        ua, da = pm_state.up_ask, pm_state.down_ask
        uas, das = pm_state.up_ask_size, pm_state.down_ask_size
        if ua is None or da is None or uas <= 0 or das <= 0:
            return
        edge = 1.0 - (ua + da) - fee(ua) - fee(da)
        if edge < MIN_EDGE:
            return
        now = time.time()
        if now - self._last_fire.get(ws, 0.0) < COOLDOWN:
            return
        self._last_fire[ws] = now

        # size BOTH legs identically — depth asymmetry must never create a
        # naked position
        want = max(5.0, math.floor(NOTIONAL))
        qty = min(want, uas, das)
        if qty < 5.0:
            return
        _event("PA_SIGNAL", bar=ws, ua=ua, da=da, uas=uas, das=das,
               edge=round(edge, 4), qty=qty)

        if not _real:
            _event("PA_PAPER_FILL", bar=ws, qty=qty, edge=round(edge, 4),
                   locked=round(edge * qty, 4))
            self._book(ws, edge * qty)
            return

        # fire both legs concurrently; FAK so we never rest a stale leg
        up_tok, dn_tok = ctx.up_token, ctx.down_token
        try:
            ru, rd = await asyncio.gather(
                self.runner.exec.fire_direct(up_tok, ua, qty),
                self.runner.exec.fire_direct(dn_tok, da, qty),
                return_exceptions=True,
            )
        except Exception as exc:
            _event("PA_ERR", bar=ws, err=str(exc)[:140])
            return
        fu = 0.0 if isinstance(ru, Exception) else (ru[5] or 0.0)
        fd = 0.0 if isinstance(rd, Exception) else (rd[5] or 0.0)
        _event("PA_FILL", bar=ws, up_filled=fu, dn_filled=fd, qty=qty,
               edge=round(edge, 4), live=True)

        paired = min(fu, fd)
        excess_tok, excess = (up_tok, fu - fd) if fu > fd else (dn_tok, fd - fu)
        if excess > 0.5:
            # a naked leg: unwind NOW rather than carry a coin flip
            try:
                oid, matched = await self.runner.exec.sell_fak(
                    excess_tok, 0.02, excess)
                _event("PA_UNWIND", bar=ws, qty=round(excess, 1),
                       matched=matched, order=oid)
            except Exception as exc:
                _event("PA_UNWIND_ERR", bar=ws, qty=round(excess, 1),
                       err=str(exc)[:140])
        if paired > 0:
            self._book(ws, edge * paired)

    def _book(self, ws: int, pnl: float) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        _event("PA_LOCKED", bar=ws, pnl=round(pnl, 4),
               day_pnl=round(self.day_pnl[day], 4))
        if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            _event("PA_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(60.0)


def main():
    from execution.runner import TakerRunner
    log.info("pairarb %s: coin=%s min_edge=%.4f $%.0f/leg",
             "LIVE" if _real else "PAPER", COIN, MIN_EDGE, NOTIONAL)
    runner = TakerRunner(PairArbStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
