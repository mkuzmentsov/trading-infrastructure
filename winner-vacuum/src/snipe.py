"""snipe.py — settlement sniper, PAPER build of exactly the logic measured in
SNIPE_REVAL.md (2026-07-31).

At bar close, lock the winner from Binance (close vs open, min-|lead| tie
guard — the same determination the vacuum runs live at 24/24). "Fire" at
close + SNIPE_FIRE_DELAY_MS. Then two parallel accountings:

  BOOK CLAIM (phantom-suspect): the winner's ask ladder <= SNIPE_CAP at fire
  time — what a live FAK would think it swept. Logged in SNIPE_FIRE only;
  NEVER booked as PnL. The reval showed the venue culls resting orders at
  close and the WS book keeps showing the corpses (4x overstatement).

  PAPER FILLS (the truth): actual taker-BUY prints on the winner at <= cap
  occurring AT/AFTER our fire time. Any ask another taker consumed after our
  fire would have been consumed by our earlier FAK instead. Prints between
  close and fire are SNIPE_MISS — the race tranche our latency loses. Asks
  cancelled unprinted are not counted (conservative).

SNIPE_SETTLE verifies the lock against gamma resolution. In PAPER it books the
print-attributed fills; in LIVE it books only what the venue's trade record
confirms (verified_filled, never poll_filled — that fabricates fills for
orders culled at close).

LIVE (2026-07-31, user go-ahead, btc only): both tokens are presigned at CAP
each bar; at close+delay we POST the winner's FAK. Risk per deal is bounded by
the ORDER ITSELF, not by our logic — a FAK with limit price CAP cannot fill
above CAP and leaves no resting remainder, so a wrong lock costs at most
SHARES*CAP (5 * 0.05 = $0.25). SNIPE_MAX_DAILY_LOSS halts the day.

Env: SNIPE_CAP(0.05) SNIPE_SHARES(5) SNIPE_FIRE_DELAY_MS(150)
SNIPE_MIN_LEAD_BPS(3) SNIPE_MAX_SPOT_AGE(10) SNIPE_MAX_DAILY_LOSS(20).
"""
from __future__ import annotations

import asyncio
import math
import os
import time

from config import BAR_SECONDS, DRY_RUN, TRAINING_EVENT_LOG_PATH, log
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

CAP = float(os.getenv("SNIPE_CAP", "0.05"))
FIRE_DELAY = float(os.getenv("SNIPE_FIRE_DELAY_MS", "150")) / 1000.0
MAX_SHARES = float(os.getenv("SNIPE_MAX_SHARES", "5000"))   # paper accounting cap
# LIVE order size, shares per deal. Max loss on a wrong lock = SHARES * CAP
# (5 * 0.05 = $0.25), because the FAK limit price cannot be exceeded.
SHARES = float(os.getenv("SNIPE_SHARES", "5"))
MIN_LEAD_BPS = float(os.getenv("SNIPE_MIN_LEAD_BPS", "3"))
# Max age of the Binance spot print used to lock the winner. NOT 2s: aggTrade
# only fires on trades, so on thin coins (sol/doge/xrp) the last print at the
# close boundary is routinely 2-5s old while the feed is perfectly healthy --
# that cost 60-70% of their bars on 2026-07-31. Staleness is anti-correlated
# with danger: no trades means no movement, so a 4s-old price on a quiet tape
# IS the close price. The real ambiguity guard is MIN_LEAD_BPS. The cap only
# rejects genuine feed outages (a 15.7s gap was observed once on doge).
# Every lock logs its spot_age so lock accuracy can be audited per bucket.
MAX_SPOT_AGE = float(os.getenv("SNIPE_MAX_SPOT_AGE", "10"))
# WINNER SIGNAL. "binance" = spot close vs bar open (the vacuum's method).
# "book" = read the post-close order book instead: after BOOK_WAIT_MS the
# market has repriced the winner's bid toward 0.99 and the loser's toward 0.
# Why offer it: on the 5 harvestable tie bars in 27-30 Jul the Binance lead was
# WRONG on 4 (leads of +2.65/+2.72/-2.76 bps all resolved the other way -- the
# documented Binance-vs-Chainlink divergence on dead-flat ties), capturing only
# 23% of the available value, while the book had it right on all 5 by +2s and
# on 3 of 5 by +0.5s. Cost: waiting burns part of the liquidity window, which
# ran -0.03..1.28s after close on those bars.
LOCK_SRC = os.getenv("SNIPE_LOCK_SRC", "binance").lower()
BOOK_WAIT = float(os.getenv("SNIPE_BOOK_WAIT_MS", "600")) / 1000.0
# minimum bid separation for the book to count as decisive
BOOK_MIN_EDGE = float(os.getenv("SNIPE_BOOK_MIN_EDGE", "0.20"))
MAX_DAILY_LOSS = float(os.getenv("SNIPE_MAX_DAILY_LOSS", "20"))
FEE_RATE = 0.07

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


class SnipeStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.bars: dict[int, dict] = {}      # ws -> state
        self.day_pnl: dict[str, float] = {}
        self._last_seq = 0
        self.halted = False

    def bind(self, runner) -> None:
        self.runner = runner
        _event("SNIPE_START", live=_real, src=LOCK_SRC,
               book_wait_ms=BOOK_WAIT * 1000, book_min_edge=BOOK_MIN_EDGE,
               cap=CAP, shares=SHARES,
               max_loss_per_deal=round(SHARES * CAP, 4),
               fire_delay_ms=FIRE_DELAY * 1000, min_lead_bps=MIN_LEAD_BPS,
               max_spot_age=MAX_SPOT_AGE, max_daily_loss=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        """Presign a FAK buy at CAP on BOTH tokens each bar. We do not know the
        winner until close, so both must be ready; at close we POST only the
        winner's. FAK + a limit price of CAP means the order can NEVER fill
        above CAP — the venue kills the unmatched remainder rather than walking
        the book. That limit is the primary risk control, not our logic."""
        if not _real:
            return []
        return [("snipe-UP", ctx.up_token, CAP, SHARES),
                ("snipe-DOWN", ctx.down_token, CAP, SHARES)] if (
                    ctx.up_token and ctx.down_token) else []

    async def on_tick(self, ctx) -> None:
        ws = ctx.ws
        end = ws + BAR_SECONDS
        now = ctx.now
        if now < end:
            return                           # nothing to do pre-close
        b = self.bars.get(ws)
        # ── lock the winner ──────────────────────────────────────────────────
        if b is None:
            lead = None
            if ctx.bar_open and ctx.spot > 0:
                lead = (ctx.spot - ctx.bar_open) / ctx.bar_open * 1e4
            if LOCK_SRC == "book":
                # wait for the market to reprice, then read it
                if now < end + BOOK_WAIT:
                    return
                ub, db = ctx.up_bid or 0.0, ctx.down_bid or 0.0
                if abs(ub - db) < BOOK_MIN_EDGE:
                    self.bars[ws] = dict(skip="book_unclear")
                    _event("SNIPE_SKIP", bar=ws, reason="book_unclear",
                           up_bid=ub, down_bid=db)
                    return
                side = "UP" if ub > db else "DOWN"
                fire_at = now                       # book already waited
                _event("SNIPE_LOCK", bar=ws, side=side, src="book",
                       up_bid=ub, down_bid=db,
                       lead_bps=None if lead is None else round(lead, 2),
                       wait_ms=round((now - end) * 1000, 0))
            else:
                if ctx.bar_open is None or ctx.spot <= 0 or ctx.spot_age > MAX_SPOT_AGE:
                    self.bars[ws] = dict(skip="no_data")
                    _event("SNIPE_SKIP", bar=ws, reason="no_data",
                           spot_age=round(ctx.spot_age, 2))
                    return
                if abs(lead) < MIN_LEAD_BPS:
                    self.bars[ws] = dict(skip="tie")
                    _event("SNIPE_SKIP", bar=ws, reason="tie",
                           lead_bps=round(lead, 2))
                    return
                side = "UP" if lead > 0 else "DOWN"
                fire_at = end + FIRE_DELAY
                _event("SNIPE_LOCK", bar=ws, side=side, src="binance",
                       lead_bps=round(lead, 2), spot_age=round(ctx.spot_age, 2))
            token = ctx.up_token if side == "UP" else ctx.down_token
            b = dict(side=side, token=token, lead=lead or 0.0, end=end,
                     spot_age=ctx.spot_age,
                     fire_at=fire_at, fired=False,
                     fills_sh=0.0, fills_ev=0.0, fills_cost=0.0, n_fills=0,
                     miss_sh=0.0, miss_ev=0.0, settled=False)
            self.bars[ws] = b
            return
        if b.get("skip") or b.get("settled"):
            return
        # ── fire: record the book claim once (phantom-suspect, not booked) ───
        if not b["fired"] and now >= b["fire_at"]:
            b["fired"] = True
            depth = ctx.up_depth if b["side"] == "UP" else ctx.down_depth
            claim = [(px, sz) for px, sz in sorted(depth.items())
                     if px <= CAP + 1e-9 and sz > 0]
            claim_sh = sum(sz for _, sz in claim)
            claim_ev = sum(sz * (1.0 - px - fee(px)) for px, sz in claim)
            b["claim_sh"] = claim_sh
            b["claim_ev"] = claim_ev
            # Both sides' bids at fire time. LOG ONLY -- not a gate. If our
            # lock is wrong the market usually already disagrees (the loser's
            # bid collapses), so this is the raw material for a future
            # "market disagrees" guard; but in a genuine late flip the book
            # may not have repriced 150ms after close, so gating on it could
            # block the very trades we want. Measure first, gate later.
            mine = ctx.up_bid if b["side"] == "UP" else ctx.down_bid
            other = ctx.down_bid if b["side"] == "UP" else ctx.up_bid
            _event("SNIPE_FIRE", bar=ws, side=b["side"],
                   delay_ms=round((now - b["end"]) * 1000, 0),
                   book_claim_sh=round(claim_sh, 1),
                   book_claim_ev=round(claim_ev, 2),
                   bid_locked=mine, bid_other=other,
                   ladder=[[round(p, 3), round(s, 1)] for p, s in claim[:4]])
            if _real and not self.halted:
                await self._fire_live(ws, b, now)
        # ── attribute prints (the honest fills) ──────────────────────────────
        from core.pm_ws import pm_state
        for t in pm_state.recent_trades:
            if t["seq"] <= self._last_seq:
                continue
            self._last_seq = t["seq"]
            if t["token_id"] != b["token"] or t.get("side") != "BUY":
                continue
            px, sz, ts = t["price"], t["size"], t["ts"]
            if px > CAP + 1e-9 or ts < b["end"]:
                continue
            if ts < b["fire_at"]:
                b["miss_sh"] += sz
                b["miss_ev"] += sz * (1.0 - px - fee(px))
                _event("SNIPE_MISS", bar=ws, px=px, sz=round(sz, 1),
                       ms_after_close=round((ts - b["end"]) * 1000, 0),
                       tok=str(b["token"])[-10:])
            elif b["fills_sh"] < MAX_SHARES:
                take = min(sz, MAX_SHARES - b["fills_sh"])
                b["fills_sh"] += take
                b["fills_cost"] += take * (px + fee(px))
                b["fills_ev"] += take * (1.0 - px - fee(px))
                b["n_fills"] += 1
                # tok + live book are logged so a paper fill can be VERIFIED
                # against the recorder later. 2026-07-31: a 5,000sh "fill" at
                # 0.01 was corroborated by NO print in any recorded market, and
                # the recorder's book for that bar had frozen -- unresolved, so
                # every paper fill now carries its own evidence.
                _ask = ctx.down_ask if b["side"] == "DOWN" else ctx.up_ask
                _bid = ctx.down_bid if b["side"] == "DOWN" else ctx.up_bid
                _event("SNIPE_PAPER_FILL", bar=ws, px=px, sz=round(take, 1),
                       ms_after_close=round((ts - b["end"]) * 1000, 0),
                       cum_sh=round(b["fills_sh"], 1),
                       tok=str(b["token"])[-10:], book_ask=_ask, book_bid=_bid)

    async def _fire_live(self, ws: int, b: dict, now: float) -> None:
        """POST the winner's presigned FAK. Unmatched remainder is killed by
        the venue; we never rest and never chase. Fills are read back from the
        AUTHORITATIVE trade record, never poll_filled (which fabricates fills
        for orders culled at close)."""
        key = "snipe-" + b["side"]
        ex = self.runner.exec
        if not ex.has_presigned(key):
            _event("SNIPE_LIVE_NOPRESIGN", bar=ws, side=b["side"])
            return
        try:
            oid, matched, post_ms, avg_px, filled = await ex.fire_presigned(key)
        except Exception as exc:
            _event("SNIPE_LIVE_ERR", bar=ws, side=b["side"], err=str(exc)[:160])
            return
        b["live_oid"] = oid
        b["live_post_ms"] = post_ms
        _event("SNIPE_LIVE_FIRE", bar=ws, side=b["side"], order=oid or "FAILED",
               matched=matched, post_ms=round(post_ms, 1),
               imm_fill=round(filled or 0.0, 1),
               imm_px=None if avg_px is None else round(avg_px, 4),
               cap=CAP, shares=SHARES)
        if oid:
            b["live_filled"] = filled or 0.0
            b["live_px"] = avg_px if avg_px else CAP

    async def _verify_live(self, ws: int, b: dict) -> float:
        """Authoritative filled shares for the live order (trade record)."""
        oid = b.get("live_oid")
        if not oid:
            return 0.0
        try:
            v = await self.runner.exec.verified_filled(oid)
        except Exception:
            v = None
        return 0.0 if v is None else float(v)

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            for ws, b in list(self.bars.items()):
                if b.get("skip"):
                    if now > ws + BAR_SECONDS + 900:
                        self.bars.pop(ws, None)
                    continue
                if b.get("settled") or now < b["end"] + 8:
                    continue
                oc = await asyncio.to_thread(outcome_up, ws)
                if oc is None:
                    if now - b["end"] > 600:
                        b["settled"] = True
                        _event("SNIPE_SETTLE_TIMEOUT", bar=ws)
                    continue
                lock_ok = (b["side"] == "UP") == oc
                pnl = b["fills_ev"] if lock_ok else -b["fills_cost"]
                live_sh = live_pnl = 0.0
                if _real:
                    live_sh = await self._verify_live(ws, b)
                    px = b.get("live_px", CAP)
                    live_pnl = (live_sh * (1.0 - px - fee(px)) if lock_ok
                                else -live_sh * (px + fee(px)))
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                booked = live_pnl if _real else pnl
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + booked
                b["settled"] = True
                _event("SNIPE_SETTLE", bar=ws, side=b["side"],
                       outcome="UP" if oc else "DOWN", lock_ok=lock_ok,
                       spot_age=round(b.get("spot_age", 0.0), 2),
                       lead_bps=round(b.get("lead", 0.0), 2),
                       fills_sh=round(b["fills_sh"], 1),
                       pnl=round(pnl, 2),
                       miss_sh=round(b["miss_sh"], 1),
                       miss_ev=round(b["miss_ev"], 2),
                       book_claim_ev=round(b.get("claim_ev", 0.0), 2),
                       live_sh=round(live_sh, 1), live_pnl=round(live_pnl, 3),
                       day_pnl=round(self.day_pnl[day], 2), live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("SNIPE_HALT", day=day,
                           day_pnl=round(self.day_pnl[day], 2))
                self.bars.pop(ws, None)


def main():
    from execution.runner import TakerRunner
    log.info("snipe %s: coin=%s src=%s cap=%.2f shares=%.0f (max loss/deal $%.2f) "
             "fire+%.0fms minLead=%.1fbps bookwait=%.0fms halt=$%.0f",
             "LIVE" if _real else "PAPER", COIN, LOCK_SRC, CAP, SHARES,
             SHARES * CAP, FIRE_DELAY * 1000, MIN_LEAD_BPS,
             BOOK_WAIT * 1000, MAX_DAILY_LOSS)
    runner = TakerRunner(SnipeStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
