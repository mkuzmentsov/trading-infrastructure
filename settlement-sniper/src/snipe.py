"""snipe.py — POST-CLOSE settlement-sniper (GTC RESTING variant).

Edge (found 2026-07-24, confirmed from data-api trades): the consistent 5m
earners buy the LOCKED winner cheap in the first ~7s AFTER bar-close. Once the bar
closes the outcome is decided (spot vs open), but stale ≤5c SELL orders on the
winning token linger uncancelled during the resolution delay. Buying them settles
at $1 = 20×+, near-riskless.

WHY GTC-REST (not FAK spray): firing a fresh signed FAK per opportunity is
latency-doomed — EIP-712 signing is ~100-300ms CPU + the CLOB is behind Cloudflare
~105ms RTT from our node = ~330ms/shot, so a faster bot sweeps each stale sell
before our POST lands. Instead we place ONE presigned GTC buy at CAP on the locked
winner right at close; it RESTS on the book and the venue matches it server-side
(zero latency) against any sell that crosses ≤CAP for the whole window — including
the late ones (fills cluster +1..+6s). Works even though PM's WS book goes dark
~0.5s post-close (we don't need to see it — the engine matches for us). Unfilled
remainder is cancelled at the window end.

Per bar:
  - pre-close: cache lead = (spot-open)/open.
  - at close: lock winner = UP if lead>0 else DOWN (skip if |lead|<MIN_LEAD_BPS).
  - place ONE presigned GTC buy at CAP on the winner (rests). Hold the window.
  - at tl_after > FIRE_MAX: read filled, cancel remainder; hold fills to settle.
  - daily realized loss <= MAX_DAILY_LOSS → halt.

Env: SNIPE_CAP(0.05) SNIPE_FIRE_MAX_SECS(7) SNIPE_NOTIONAL(5)
     SNIPE_MIN_LEAD_BPS(1) SNIPE_MAX_DAILY_LOSS(20). FAV_ORDER_TYPE must be 'gtc'.
     Runner needs POST_CLOSE_GRACE_SECS >= FIRE_MAX (+slack), e.g. 10.
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

CAP = float(os.getenv("SNIPE_CAP", "0.05"))
FIRE_MAX = float(os.getenv("SNIPE_FIRE_MAX_SECS", "7"))
NOTIONAL = float(os.getenv("SNIPE_NOTIONAL", "5"))
MIN_LEAD_BPS = float(os.getenv("SNIPE_MIN_LEAD_BPS", "1"))
MAX_DAILY_LOSS = float(os.getenv("SNIPE_MAX_DAILY_LOSS", "20"))

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _shares(usd: float) -> float:
    return max(5.0, math.floor(usd / max(CAP, 0.01)))


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


class SnipeStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.open_bets: dict[int, dict] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        # per-bar working state
        self._last_lead: dict[int, float] = {}   # ws -> last pre-close lead
        self._winner: dict[int, str] = {}        # ws -> "UP"/"DOWN" (locked)
        self._order: dict[int, str] = {}         # ws -> resting order id (None while placing)
        self._imm_fill: dict[int, float] = {}    # ws -> shares filled on placement (taker cross)
        self._imm_px: dict[int, float] = {}      # ws -> avg price of the placement cross
        self._done: set[int] = set()             # ws -> firing lifecycle complete
        self.settled: set[int] = set()           # ws -> settle_loop resolved

    def bind(self, runner) -> None:
        self.runner = runner
        _event("SNIPE_START", live=_real, mode="gtc_rest", cap=CAP, fire_max=FIRE_MAX,
               notional=NOTIONAL, min_lead_bps=MIN_LEAD_BPS, max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        # presign BOTH sides at the cap; at close we POST the winner's as GTC (rests)
        sz = _shares(NOTIONAL)
        reqs = []
        if ctx.up_token:
            reqs.append(("snipe-UP", ctx.up_token, CAP, sz))
        if ctx.down_token:
            reqs.append(("snipe-DOWN", ctx.down_token, CAP, sz))
        return reqs

    def _prune(self, ws: int) -> None:
        for d in (self._last_lead, self._winner, self._order, self._imm_fill, self._imm_px):
            for k in [k for k in d if k < ws - 3600]:
                d.pop(k, None)
        self._done = {k for k in self._done if k >= ws - 3600}

    async def on_tick(self, ctx) -> None:
        ws = ctx.ws
        tl = ctx.t_left

        # ── PRE-CLOSE: cache the lead so we can lock the winner at close ──────
        if tl >= 0:
            if ctx.bar_open and ctx.spot > 0 and ctx.spot_age <= 5.0:
                self._last_lead[ws] = (ctx.spot - ctx.bar_open) / ctx.bar_open
            return

        # ── POST-CLOSE window ────────────────────────────────────────────────
        if self.halted or ws in self._done:
            return
        tl_after = -tl

        # window over → read fill, cancel remainder, finalize
        if tl_after > FIRE_MAX:
            await self._finalize(ws)
            return

        # lock the winner once (from the last pre-close lead)
        if ws not in self._winner:
            lead = self._last_lead.get(ws)
            if lead is None or abs(lead) * 1e4 < MIN_LEAD_BPS:
                self._done.add(ws)
                _event("SNIPE_SKIP", bar=ws, reason="no_lead_or_tie",
                       lead_bps=None if lead is None else round(lead * 1e4, 1))
                return
            self._winner[ws] = "UP" if lead > 0 else "DOWN"
            _event("SNIPE_LOCK", bar=ws, winner=self._winner[ws],
                   lead_bps=round(lead * 1e4, 1), tl_after=round(tl_after, 2))

        # place the resting GTC bid ONCE (guard re-entry: mark placing before await)
        if ws not in self._order:
            self._order[ws] = None
            win = self._winner[ws]
            token = ctx.up_token if win == "UP" else ctx.down_token
            key = f"snipe-{win}"
            t0 = time.time()
            try:
                if self.runner.exec.has_presigned(key):
                    oid, matched, post_ms, avg_px, filled = \
                        await self.runner.exec.fire_presigned(key)
                else:
                    oid, matched, _s, post_ms, avg_px, filled = \
                        await self.runner.exec.fire_direct(token, CAP, _shares(NOTIONAL))
            except Exception as exc:
                _event("SNIPE_ERR", bar=ws, side=win, err=str(exc)[:160])
                return
            self._order[ws] = oid
            self._imm_fill[ws] = filled or 0.0
            self._imm_px[ws] = avg_px if avg_px else None
            _event("SNIPE_REST", bar=ws, side=win, order=oid or "FAILED",
                   imm_fill=round(filled or 0.0, 1),
                   imm_px=None if avg_px is None else round(avg_px, 4),
                   tl_after=round(tl_after, 2), post_ms=round(post_ms, 1),
                   matched=matched, live=_real)
        # else: order is resting — the venue matches it for us, nothing to do

    async def _finalize(self, ws: int) -> None:
        if ws in self._done:
            return
        self._done.add(ws)                       # sync guard before any await
        if ws not in self._winner:
            self._prune(ws)
            return
        oid = self._order.get(ws)
        imm = self._imm_fill.get(ws, 0.0)
        imm_px = self._imm_px.get(ws)
        filled = imm
        if oid:
            pf = await self.runner.exec.poll_filled(oid)
            if pf is not None:
                filled = max(filled, pf)
            await self.runner.exec.cancel(oid)
        win = self._winner[ws]
        if filled and filled > 0:
            # weighted avg cost: the placement cross (taker) at its true avg px,
            # any rested fills assumed at CAP (bid price). Gives real fill economics.
            rested = max(0.0, filled - imm)
            cost = imm * (imm_px if imm_px else CAP) + rested * CAP
            fill_px = cost / filled
            self.open_bets[ws] = {"side": win, "fill_px": fill_px,
                                  "fill_qty": filled, "order_id": oid}
            _event("SNIPE_FILL", bar=ws, side=win, filled=round(filled, 1),
                   fill_px=round(fill_px, 4), taker_cross=round(imm, 1),
                   taker_px=None if imm_px is None else round(imm_px, 4),
                   rested_fill=round(rested, 1), order=oid, live=_real)
        else:
            _event("SNIPE_NOFILL", bar=ws, side=win, order=oid or "FAILED")
        self._prune(ws)

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
                        _event("SNIPE_SETTLE_TIMEOUT", bar=ws)
                    continue
                won = (bet["side"] == "UP") == oc
                q = bet["fill_qty"] or 0.0
                pnl = q * ((1.0 if won else 0.0) - bet["fill_px"])
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.settled.add(ws)
                _event("SNIPE_SETTLE", bar=ws, side=bet["side"],
                       outcome="UP" if oc else "DOWN", won=won,
                       fill_px=round(bet["fill_px"], 4), qty=round(q, 1),
                       pnl=round(pnl, 3), day_pnl=round(self.day_pnl[day], 2),
                       live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("SNIPE_HALT", day=day, day_pnl=round(self.day_pnl[day], 2),
                           max_dd=MAX_DAILY_LOSS)


def main():
    from execution.runner import TakerRunner
    log.info("snipe %s GTC-REST: coin=%s cap=%.2f fire_max=%.1fs $%.0f/deal "
             "minLead=%.0fbps maxDD=$%.0f", "LIVE" if _real else "PAPER", COIN, CAP,
             FIRE_MAX, NOTIONAL, MIN_LEAD_BPS, MAX_DAILY_LOSS)
    runner = TakerRunner(SnipeStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
