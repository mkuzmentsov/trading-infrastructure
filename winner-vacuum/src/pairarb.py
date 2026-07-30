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

# A leg that comes back short has to be sold immediately, but the shares are
# not credited to the proxy the instant the CLOB matches — the first sell comes
# back "not enough balance / allowance: balance: 0" (live, 2026-07-30 19:07).
# One attempt is therefore not an unwind: retry until the credit lands.
UNWIND_TRIES = int(os.getenv("PA_UNWIND_TRIES", "8"))
UNWIND_BACKOFF = float(os.getenv("PA_UNWIND_BACKOFF", "2.0"))

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def fee(p: float) -> float:
    return FEE_RATE * p * (1.0 - p)


def outcome_up(ws: int):
    """Gamma resolution: True=UP won, False=DOWN, None=unresolved."""
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


class PairArbStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.halted = False
        self.day_pnl: dict[str, float] = {}
        self._last_fire: dict[int, float] = {}
        self._done: set[int] = set()
        self._naked: dict[int, dict] = {}        # ws -> unhedged leg carried

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
        if ws in self._naked:
            return             # never stack a second pair on an unhedged bar
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
        if fu > fd:
            excess_tok, excess, side, px = up_tok, fu - fd, "UP", ua
        else:
            excess_tok, excess, side, px = dn_tok, fd - fu, "DOWN", da
        if excess > 0.5:
            # A naked leg. Book the WORST CASE (the whole cost) against the day
            # immediately: until it is unwound or resolves, that is what we can
            # lose, and the daily-loss halt has to be able to see it. Booking
            # only edge*paired left the halt blind to the one loss mode that has
            # actually happened live (2026-07-30: naked 7.9sh, halt saw $0).
            avg = (ru if fu > fd else rd)
            avg_px = None if isinstance(avg, Exception) else avg[4]
            cost = excess * (avg_px if avg_px else px)
            self._naked[ws] = dict(tok=excess_tok, side=side, qty=excess,
                                   cost=cost, provisional=-cost)
            self._book(ws, -cost, kind="naked_provisional")
            asyncio.create_task(self._unwind(ws))
        if paired > 0:
            self._book(ws, edge * paired, kind="paired")

    async def _unwind(self, ws: int) -> None:
        """Sell the naked leg, retrying while the CLOB credit settles."""
        n = self._naked.get(ws)
        if not n:
            return
        from core.pm_ws import pm_state
        for attempt in range(1, UNWIND_TRIES + 1):
            bid = pm_state.up_bid if n["side"] == "UP" else pm_state.down_bid
            try:
                oid, matched = await self.runner.exec.sell_fak(
                    n["tok"], 0.02, n["qty"])
            except Exception as exc:
                _event("PA_UNWIND_ERR", bar=ws, qty=round(n["qty"], 1),
                       attempt=attempt, err=str(exc)[:140])
                await asyncio.sleep(UNWIND_BACKOFF * attempt)
                continue
            if not oid or not matched:
                # post_signed_sell_fak SWALLOWS everything except the balance
                # error and returns (None, False) — e.g. "no orders found to
                # match with FAK order" when the bid side is empty. A missing
                # order id or an unmatched FAK is a FAILED unwind, never a
                # silent success (same trap as the buy path, f8ad3f2).
                _event("PA_UNWIND_ERR", bar=ws, qty=round(n["qty"], 1),
                       attempt=attempt, err="no order id / FAK unmatched")
                await asyncio.sleep(UNWIND_BACKOFF * attempt)
                continue
            proceeds = n["qty"] * (bid or 0.0)
            _event("PA_UNWIND", bar=ws, qty=round(n["qty"], 1), order=oid,
                   matched=matched, attempt=attempt,
                   proceeds_est=round(proceeds, 3))
            # correct the provisional worst case by the (estimated) proceeds
            self._book(ws, proceeds, kind="unwind_recovery")
            self._naked.pop(ws, None)
            return
        # exhausted: the leg rides to resolution and settle_loop books the truth
        _event("PA_UNWIND_GIVEUP", bar=ws, qty=round(n["qty"], 1),
               cost=round(n["cost"], 3))

    def _book(self, ws: int, pnl: float, kind: str = "paired") -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
        _event("PA_LOCKED", bar=ws, pnl=round(pnl, 4), kind=kind,
               day_pnl=round(self.day_pnl[day], 4))
        if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            _event("PA_HALT", day=day, day_pnl=round(self.day_pnl[day], 2))

    async def settle_loop(self) -> None:
        """Resolve carried naked legs and replace the provisional worst case
        with the real payout, so day_pnl converges to the truth."""
        while True:
            await asyncio.sleep(60.0)
            for ws in list(self._naked):
                n = self._naked[ws]
                if time.time() < ws + 300 + 30:
                    continue           # bar has not closed long enough
                oc = await asyncio.to_thread(outcome_up, ws)
                if oc is None:
                    if time.time() - (ws + 300) > 900:
                        self._naked.pop(ws, None)
                        _event("PA_SETTLE_TIMEOUT", bar=ws)
                    continue
                won = (n["side"] == "UP") == oc
                payout = n["qty"] if won else 0.0
                _event("PA_SETTLE", bar=ws, side=n["side"], won=won,
                       qty=round(n["qty"], 1), cost=round(n["cost"], 3),
                       payout=round(payout, 3),
                       realised=round(payout - n["cost"], 3))
                # provisional booked -cost already; add the payout back
                self._book(ws, payout, kind="naked_settle")
                self._naked.pop(ws, None)


def main():
    from execution.runner import TakerRunner
    log.info("pairarb %s: coin=%s min_edge=%.4f $%.0f/leg",
             "LIVE" if _real else "PAPER", COIN, MIN_EDGE, NOTIONAL)
    runner = TakerRunner(PairArbStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
