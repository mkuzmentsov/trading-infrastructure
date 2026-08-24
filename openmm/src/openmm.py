"""openmm — 5m two-sided MAKER, .44–.56 band, first minute, imbalance-gated.

Research: docs/strat-openmm-5m.md (built 2026-08-19). Short version:

  The maker side of this venue is ~break-even in aggregate, with losses
  concentrated in specific cells. The first minute of the bar (+0.41 c/sh) and
  the coin-flip band are the survivable ones — and the coin-flip band is also
  where the maker REBATE peaks (fee ∝ p(1−p) ⇒ 0.35 c/sh at 0.50).

  Plain two-sided quoting there dies on latency: the venue's order round trip
  is 190ms measured, and at that speed every configuration loses (§10). What
  rescues it is the QUEUE-IMBALANCE gate (§11c): on the field's real fills,
  maker PnL runs −1.27 c/sh when our side's queue is thin vs the opposite and
  +2.64 when it is thick — monotone over 6 buckets, t=+3.42 on 105k fills.
  Gating on it flips the sim from −$65/day to +$151/day AND makes it
  latency-insensitive (d=0.4 ≈ d=0.2), because it only quotes when the book is
  stably in our favour, so a stale quote stops mattering.

  ⚠️ The book is MIRRORED (up_bid_size ≡ down_ask_size), so imb_UP ≡ −imb_DOWN:
  this gate is inherently ONE-SIDED and gives up most of the pair engine.
  ~85% of PnL becomes a directional residual. This is NOT a proven strategy —
  it is a pilot to measure real fill rates, queue behaviour and whether the
  maker rebate credits as modelled (§11e).

Discipline inherited from poolfarm (hard-won, do not "improve" without data):
  * HOLD to redemption. No exit quotes, no partner-cancel — exit round-trips
    turned neutral +EV holds into bad directional bets (96% of a −$111 loss).
  * Never quote above the touch; post-only makes the venue enforce it.
  * Sticky per-UTC-day halt latch (a post-halt resolve once un-halted the bot).
  * Gate on BOOK FRESHNESS — a dead WS keeps its last top-of-book and
    manufactures phantom fills (ledger #15).

Env: PM_OM_SIZE(5) PM_OM_BAND_LO(0.44) PM_OM_BAND_HI(0.56)
     PM_OM_TL_HI(297) PM_OM_TL_LO(240) PM_OM_IMB(0.2) PM_OM_IMB_HYST(0.15)
     PM_OM_FV(0.08) PM_OM_PULL_BPS(0.1) PM_OM_PULL_WIN(0.5)
     PM_OM_MAX_INV_SH(20) PM_OM_LOOP(0.25) LIVE_MAX_DAILY_LOSS_USD halt.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
from collections import deque

from config import (BAR_SECONDS, DRY_RUN, LIVE_MAX_DAILY_LOSS_USD,
                    LIVE_TRADING, TRAINING_EVENT_LOG_PATH, log)
from core.binance_ws import binance_state, run_binance_ws
from core.gamma import grid_window_start
from core.pm_ws import pm_state, run_pm_ws
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
_real = LIVE_TRADING and not DRY_RUN

SIZE = float(os.getenv("PM_OM_SIZE", "5"))
BAND_LO = float(os.getenv("PM_OM_BAND_LO", "0.44"))
BAND_HI = float(os.getenv("PM_OM_BAND_HI", "0.56"))
TL_HI = float(os.getenv("PM_OM_TL_HI", "297"))     # skip the first ~3s: stale
TL_LO = float(os.getenv("PM_OM_TL_LO", "240"))     # pre-open orders get swept
IMB_THR = float(os.getenv("PM_OM_IMB", "0.2"))
IMB_HYST = float(os.getenv("PM_OM_IMB_HYST", "0.15"))
FV_THR = float(os.getenv("PM_OM_FV", "0.08"))
PULL_BPS = float(os.getenv("PM_OM_PULL_BPS", "0.1"))
PULL_WIN = float(os.getenv("PM_OM_PULL_WIN", "0.5"))
MAX_INV_SH = float(os.getenv("PM_OM_MAX_INV_SH", "20"))
# Effective reaction = LOOP + network(~91ms measured). At 0.25 that is ~0.34s,
# but the sim gains +0.20 c/sh going 0.2s -> 0.1s (pairfirst.py, 6 coins/19d:
# GATE+ceil +1.073 -> +1.277). The tick is a few dict lookups; fill polling is
# separate (FILL_POLL), so a 0.1s loop costs nothing.
LOOP = float(os.getenv("PM_OM_LOOP", "0.10"))
BOOK_MAX_AGE = float(os.getenv("PM_OM_BOOK_MAX_AGE", "5.0"))
# ANTI-THRASH (added 2026-08-19 after the first paper run: 49 placements in
# ~50s). Live top-of-book sizes update per WS event and are far noisier than
# the 100ms mrec snapshots the sim was calibrated on, so `imb` whipsaws across
# the gate line and place->cancel->place churns. At a 190ms venue round trip
# that is unshippable. MIN_REST holds a quote against SOFT gate flips
# (imb/fv/pull/band); COOLDOWN spaces re-placement after any cancel. Hard
# reasons (window close, halt, fill) always act immediately.
# Values are MEASURED, not guessed (backtest/mm5m/minrest.py, 6 coins/19d at
# the real 190ms latency): 1.0/0.5 gives +1.946 c/sh t=+3.36 vs +1.669/+3.25
# ungated-by-rest, i.e. anti-thrash slightly HELPS. 1.5/1.0 drops to +1.387.
# PAIR-COST CEILING (ported from poolfarm after openmm's FIRST live pair,
# 2026-08-19 18:35: filled DOWN@0.56 then UP@0.55 = 1.11 for a guaranteed $1.00
# payout, a locked -$0.55). Each leg was inside its OWN band at its own moment;
# only the SUM is the loss. Once one leg fills at p, the opposite leg is capped
# at (PAIR_CEIL - p) so any completed pair is guaranteed to cost < 1.00.
# poolfarm learned this the same way (whipsaw bar, 1.29 pair, -$14.50).
PAIR_CEIL = float(os.getenv("PM_OM_PAIR_CEIL", "0.985"))
# fill-detection interval. At 1.0s a fill sat undetected for up to a second,
# so 50% of cancels returned ok=False ("already filled") and the pair ceiling
# quoted against a stale book. 0.35s costs ~3 req/s per live quote.
FILL_POLL = float(os.getenv("PM_OM_FILL_POLL", "0.35"))
MIN_REST = float(os.getenv("PM_OM_MIN_REST", "1.0"))
COOLDOWN = float(os.getenv("PM_OM_COOLDOWN", "0.5"))
_SOFT = ("imb", "fv", "pull", "band", "repin", "pairceil")
# Order states that mean the order is DONE at the venue. A failed cancel on one
# of these must DROP the order, not re-track it: re-tracking a terminal order
# re-occupies quotes[role], blocks new quotes on that side, and on window-close
# the cancel fails again and re-adds it -> the side freezes for good.
# (Live 2026-08-19 22:25: PF_OM_CANCEL_RETRY status=matched.)
_TERMINAL = ("matched", "filled", "cancelled", "canceled", "expired",
             "rejected", "invalid")

# σ(tl) in bps — grid-searched against realised outcomes (backtest/mm5m/
# fairval.py). Used only for the fv gate; the model does NOT beat the book at
# predicting outcomes, but (Φ(lead/σ) − mid) predicts the mid's own DRIFT
# (corr +0.05/+0.08/+0.12 at 1/3/10s), i.e. which side is about to be run over.
_SIGMA = [(0, 2.00), (15, 2.50), (30, 2.75), (45, 3.00), (60, 3.25), (75, 3.50),
          (90, 3.50), (105, 4.00), (120, 4.25), (135, 4.75), (150, 5.25),
          (165, 5.75), (180, 6.00), (195, 6.50), (210, 6.75), (225, 7.00),
          (240, 7.75), (255, 8.25), (270, 8.50), (285, 8.25)]

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _sigma(tl: float) -> float:
    s = _SIGMA[-1][1]
    for lo, v in _SIGMA:
        if tl >= lo:
            s = v
    return s


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


class Quote:
    __slots__ = ("oid", "token", "px", "sh", "placed", "role", "booked")

    def __init__(self, oid, token, px, sh, role):
        self.oid = oid
        self.token = token
        self.px = px
        self.sh = sh
        self.placed = time.time()
        self.role = role                      # "up" | "down"
        self.booked = 0.0                     # shares already accounted


class OpenMM:
    def __init__(self):
        self.clob = None
        self.quotes: dict[str, Quote] = {}    # role -> Quote
        self.inv: dict[str, float] = {}       # token -> shares held
        self.inv_cost: dict[str, float] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self.n_quotes = 0
        self.n_fills = 0
        self.n_rejected = 0
        self.bar_filled: dict[tuple, float] = {}   # (ws, role) -> shares filled
        self.bar_cost: dict[tuple, float] = {}     # (ws, role) -> $ spent
        self.lead_h: deque = deque(maxlen=400)     # (ts, lead_bps)
        self._halt_since = 0.0
        self._fill_check = 0.0
        self._cool: dict[str, float] = {}   # role -> no-replace-until ts
        # ⚠️ A restart wipes bar_filled / inv / day_pnl, which ARE the per-bar
        # cap, the inventory cap and the daily halt. Restarting mid-bar in the
        # 19:20 bar (2026-08-19) re-armed all three and took 55 shares against
        # a designed 10. Sit out the bar we start in; state is unknowable.
        self._start_ws = None
        self._state_path = os.getenv("PM_OM_STATE",
                                     "/app/logs/openmm_state.json")
        self._load_state()

    # ── crash-safe state ────────────────────────────────────────────────────
    def _load_state(self):
        """day_pnl must survive restarts or the daily halt is unenforceable."""
        try:
            import json as _j
            d = _j.load(open(self._state_path))
            self.day_pnl = {k: float(v) for k, v in (d.get("day_pnl") or {}).items()}
            self._halt_day = d.get("halt_day")
            log.info("openmm state restored: day_pnl=%s halt_day=%s",
                     self.day_pnl, self._halt_day)
        except Exception:
            pass

    def _save_state(self):
        try:
            import json as _j
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as f:
                _j.dump({"day_pnl": self.day_pnl,
                         "halt_day": getattr(self, "_halt_day", None)}, f)
            os.replace(tmp, self._state_path)
        except Exception as exc:
            log.warning("openmm state save failed: %s", exc)

    # ── market state ────────────────────────────────────────────────────────
    def _book_fresh(self, now: float) -> bool:
        """Ledger #15: a dead WS keeps its last top-of-book and manufactures
        phantom fills. Refuse to quote on a stale book."""
        if not pm_state.ready:
            return False
        age = now - max(pm_state.last_up_book_ts, pm_state.last_down_book_ts)
        return age <= BOOK_MAX_AGE

    def _lead_bps(self, ws: int):
        if not binance_state.ready or binance_state.age() > 5.0:
            return None
        op = binance_state.bar_open_at(ws)
        if not op or binance_state.current_price <= 0:
            return None
        return (binance_state.current_price - op) / op * 1e4

    def _spot_move(self, now: float):
        """Signed bps change in lead over PULL_WIN (+ = spot rising ⇒ UP favoured)."""
        if not self.lead_h:
            return None
        cutoff = now - PULL_WIN
        old = None
        for ts, lb in self.lead_h:
            if ts <= cutoff:
                old = lb
            else:
                break
        if old is None:
            return None
        return self.lead_h[-1][1] - old

    def _side_state(self, role: str):
        """(token, bid, my_queue, opposite_queue) for one side.
        Our order rests on this token's BID; the opposite queue is its ASK."""
        if role == "up":
            return (pm_state.token_id_up, pm_state.up_bid,
                    pm_state.up_bid_size, pm_state.up_ask_size)
        return (pm_state.token_id_down, pm_state.down_bid,
                pm_state.down_bid_size, pm_state.down_ask_size)

    # ── order plumbing ──────────────────────────────────────────────────────
    def _book_fill(self, q: "Quote", matched: float, role: str, ws: int,
                   how: str):
        """Single path for recording a fill, from EITHER the poll or a failed
        cancel. HOLD to redemption — no exit quote (poolfarm discipline)."""
        self.n_fills += 1
        self.inv[q.token] = self.inv.get(q.token, 0.0) + matched
        self.inv_cost[q.token] = self.inv_cost.get(q.token, 0.0) + matched * q.px
        k = (ws, role)
        self.bar_filled[k] = self.bar_filled.get(k, 0.0) + matched
        self.bar_cost[k] = self.bar_cost.get(k, 0.0) + matched * q.px
        if len(self.bar_filled) > 64:
            self.bar_filled = {kk: v for kk, v in self.bar_filled.items()
                               if kk[0] >= ws - 3600}
            self.bar_cost = {kk: v for kk, v in self.bar_cost.items()
                             if kk[0] >= ws - 3600}
        _event("PF_OM_FILL", role=role, px=q.px, sh=matched,
               oid=(q.oid or "")[:16], how=how)

    async def _cancel(self, role: str, reason: str):
        """⚠️ A FAILED cancel is not a no-op — the order has usually already
        FILLED in the race (live 2026-08-19 18:45:10: cancel ok=False on a
        down@0.47 that had just filled; we dropped it from tracking, so the
        pair ceiling never saw that leg and let up@0.54 through = a 1.01 pair).
        Never discard an order on a failed cancel: reconcile it from the venue.
        """
        from engine.clob import cancel_order, fetch_order_status
        q = self.quotes.pop(role, None)
        if q is None:
            return
        ok = True
        cms = 0.0
        if _real and q.oid:
            # measure CANCEL round trip: the sim assumes 190ms (= the measured
            # PLACE latency). If cancels are slower, our quotes are exposed
            # longer than modelled and the gates protect less than simulated.
            _t0 = time.time()
            ok = await asyncio.to_thread(cancel_order, self.clob, q.oid)
            cms = (time.time() - _t0) * 1000.0
            if not ok:
                st = None
                try:
                    st = await asyncio.to_thread(fetch_order_status, self.clob,
                                                 q.oid)
                except Exception:
                    pass
                matched = float((st or {}).get("size_matched") or 0)
                status = str((st or {}).get("status", "")).lower()
                if matched > q.booked + 1e-9:
                    self._book_fill(q, matched - q.booked, role,
                                    grid_window_start(time.time()),
                                    "cancel_race")
                    q.booked = matched
                elif st is not None and status in _TERMINAL:
                    pass                       # done at the venue — drop it
                elif st is not None:
                    self.quotes[role] = q      # genuinely still live — re-track
                    _event("PF_OM_CANCEL_RETRY", role=role, px=q.px,
                           status=status, oid=q.oid[:16])
        _event("PF_OM_CANCEL", role=role, px=q.px, reason=reason, ok=ok,
               ms=round(cms, 1), rest=round(time.time() - q.placed, 2),
               oid=(q.oid or "")[:16])

    async def _place(self, role: str, token: str, px: float, sh: float):
        """GTC POST-ONLY buy. post_only makes the venue REJECT a crossing order
        rather than fill it as taker — fill-or-skip by design."""
        from engine.clob import place_limit_order
        if not (0.01 <= px <= 0.99) or not token:
            return
        oid = None
        _t0 = time.time()
        pms = 0.0
        if _real:
            try:
                oid = await asyncio.to_thread(
                    place_limit_order, self.clob, token, "BUY", sh, px)
                pms = (time.time() - _t0) * 1000.0
            except Exception as exc:
                _event("PF_OM_ERR", where="place", role=role, err=str(exc)[:140])
                return
            if not oid:                      # post-only rejection = skip
                self.n_rejected += 1
                _event("PF_OM_REJECT", role=role, px=px)
                return
        q = Quote(oid, token, px, sh, role)
        self.quotes[role] = q
        self.n_quotes += 1
        _event("PF_OM_QUOTE", role=role, px=px, sh=sh, ms=round(pms, 1),
               oid=(oid or "paper")[:16], live=_real)

    async def _check_fills(self, ws: int):
        from engine.clob import fetch_order_status
        for role, q in list(self.quotes.items()):
            if not _real or not q.oid:
                continue
            try:
                st = await asyncio.to_thread(fetch_order_status, self.clob, q.oid)
            except Exception:
                continue
            if not st:
                continue
            status = str(st.get("status", "")).lower()
            matched = float(st.get("size_matched") or 0)
            if matched > q.booked + 1e-9:
                newly = matched - q.booked
                q.booked = matched
                # ⚠️ a PARTIAL fill leaves the remainder RESTING at the venue.
                # Popping it here (the original bug) orphaned live size: it
                # could fill again unseen, defeating the pair ceiling and the
                # per-bar cap. Only stop tracking once it is fully matched.
                if matched >= q.sh - 1e-9:
                    self.quotes.pop(role, None)
                self._book_fill(q, newly, role, ws, "poll")
            elif status in ("cancelled", "canceled"):
                self.quotes.pop(role, None)

    # ── main loop ───────────────────────────────────────────────────────────
    async def farm_loop(self):
        while True:
            await asyncio.sleep(LOOP)
            try:
                await self._tick()
            except Exception as exc:
                log.exception("openmm: %s", exc)
                _event("PF_OM_ERR", where="tick", err=str(exc)[:140])

    async def _tick(self):
        now = time.time()
        ws = grid_window_start(now)
        end = ws + BAR_SECONDS
        tl = end - now
        day = time.strftime("%Y-%m-%d", time.gmtime())

        # sticky per-UTC-day halt latch (the latched day is the only authority)
        if getattr(self, "_halt_day", None) == day:
            for role in list(self.quotes):
                await self._cancel(role, "halt")
            return
        if self.day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            if not self._halt_since:
                self._halt_since = now
            if now - self._halt_since < 6.0:      # let paired resolves land
                return
            if self.day_pnl.get(day, 0.0) > -LIVE_MAX_DAILY_LOSS_USD:
                self._halt_since = 0.0
                return
            self.halted = True
            self._halt_day = day
            self._save_state()
            _event("PF_OM_HALT", day=day,
                   day_pnl=round(self.day_pnl.get(day, 0.0), 2))
            for role in list(self.quotes):
                await self._cancel(role, "halt")
            return
        self._halt_since = 0.0

        lead = self._lead_bps(ws)
        if lead is not None:
            self.lead_h.append((now, lead))

        if self._start_ws is None:
            self._start_ws = ws
            _event("PF_OM_SITOUT", bar=ws, reason="startup_bar")
        in_window = (ws != self._start_ws
                     and pm_state.market_end_ts == end and TL_LO <= tl <= TL_HI
                     and self._book_fresh(now)
                     and sum(self.inv.values()) < MAX_INV_SH)
        if not in_window:
            for role in list(self.quotes):
                await self._cancel(role, "window")
            return

        if now - self._fill_check >= FILL_POLL:
            self._fill_check = now
            await self._check_fills(ws)

        ub, ua = pm_state.up_bid, pm_state.up_ask
        if not (0 < ub < 1 and 0 < ua < 1 and ua > ub):
            return
        mid = (ub + ua) / 2.0
        mv = self._spot_move(now)
        edge = None if lead is None else _phi(lead / _sigma(tl)) - mid

        for role in ("up", "down"):
            token, bid, myq, oppq = self._side_state(role)
            if not token or not (0 < bid < 1):
                continue
            px = round(bid, 2)
            cur = self.quotes.get(role)
            tot = (myq or 0.0) + (oppq or 0.0)
            imb = ((myq - oppq) / tot) if tot > 0 else 0.0

            # ── gates (all evaluated at quote time) ──────────────────────────
            reason = None
            if not (BAND_LO <= px <= BAND_HI):
                reason = "band"
            elif self.bar_filled.get((ws, role), 0.0) >= SIZE - 1e-9:
                reason = "filled"          # one order per side per bar
            elif mv is not None and (-mv if role == "up" else mv) >= PULL_BPS:
                reason = "pull"            # spot moving against this side
            elif edge is not None and (edge if role == "up" else -edge) < -FV_THR:
                reason = "fv"              # model says this side is overpriced
            else:
                # pair-cost ceiling: never complete a pair that costs >= $1
                other = "down" if role == "up" else "up"
                osh = self.bar_filled.get((ws, other), 0.0)
                p_other = None
                if osh > 1e-9:
                    p_other = self.bar_cost.get((ws, other), 0.0) / osh
                # a LIVE quote on the other side may fill at any instant and our
                # fill detection lags a poll interval — treat it as already
                # filled for ceiling purposes (this staleness is what let the
                # 1.01 pair through at 18:45). Costs nothing but a few skipped
                # quotes; a bad pair is a GUARANTEED loss.
                oq = self.quotes.get(other)
                if oq is not None:
                    p_other = max(p_other or 0.0, oq.px)
                if p_other is not None and px > PAIR_CEIL - p_other + 1e-9:
                    reason = "pairceil"
            # imbalance gate carries hysteresis so we do not thrash on the line
            if reason is None:
                need = IMB_THR - (IMB_HYST if cur is not None else 0.0)
                if imb < need:
                    reason = "imb"

            if reason is not None:
                # SOFT gate flips do not yank a quote that has not rested yet —
                # otherwise noisy top-of-book sizes churn orders (see MIN_REST).
                if cur is not None and not (reason in _SOFT
                                            and now - cur.placed < MIN_REST):
                    await self._cancel(role, reason)
                    self._cool[role] = now + COOLDOWN
                continue
            if cur is None:
                if now >= self._cool.get(role, 0.0):
                    await self._place(role, token, px, SIZE)
            elif abs(cur.px - px) > 1e-9 and now - cur.placed >= MIN_REST:
                # RE-PIN: the touch moved. Re-pinning is essential (sim:
                # never-re-pin is −3.44 c/sh vs −0.47) and costs ~8 orders/bar.
                await self._cancel(role, "repin")
                await self._place(role, token, px, SIZE)

    # ── bookkeeping loops ───────────────────────────────────────────────────
    async def resolve_loop(self):
        """Realize PnL from ENDED bars so the inventory cap frees and the daily
        halt sees the truth (the sweeper redeems winners on-chain)."""
        import json as _json
        import urllib.request as _rq
        from core.gamma import window_slug
        known: dict[str, int] = {}
        while True:
            await asyncio.sleep(20.0)
            try:
                if pm_state.token_id_up:
                    known[pm_state.token_id_up] = pm_state.market_end_ts - BAR_SECONDS
                if pm_state.token_id_down:
                    known[pm_state.token_id_down] = pm_state.market_end_ts - BAR_SECONDS
                now = time.time()
                for token, sh in list(self.inv.items()):
                    if sh <= 1e-6:
                        self.inv.pop(token, None)
                        self.inv_cost.pop(token, None)
                        continue
                    ws = known.get(token)
                    if ws is None or now < ws + BAR_SECONDS + 60:
                        continue
                    if token in (pm_state.token_id_up, pm_state.token_id_down):
                        continue
                    cost = self.inv_cost.get(token, 0.0)
                    url = ("https://gamma-api.polymarket.com/markets?slug="
                           + window_slug(ws) + "&closed=true")
                    req = _rq.Request(url, headers={"User-Agent": "openmm"})
                    d = _json.loads(_rq.urlopen(req, timeout=10).read())
                    if not d or not d[0].get("closed"):
                        continue
                    op = d[0]["outcomePrices"]
                    op = _json.loads(op) if isinstance(op, str) else op
                    up_won = str(op[0]) in ("1", "1.0")
                    try:
                        toks = _json.loads(d[0]["clobTokenIds"])
                    except Exception:
                        toks = []
                    won = (token == toks[0]) == up_won if toks else False
                    pnl = sh * 1.0 - cost if won else -cost
                    day = time.strftime("%Y-%m-%d", time.gmtime())
                    self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                    self._save_state()
                    self.inv.pop(token, None)
                    self.inv_cost.pop(token, None)
                    _event("PF_OM_RESOLVE", bar=ws, won=won, sh=round(sh, 1),
                           cost=round(cost, 3), pnl=round(pnl, 4),
                           day_pnl=round(self.day_pnl.get(day, 0.0), 3))
            except Exception as exc:
                _event("PF_OM_ERR", where="resolve", err=str(exc)[:140])

    async def rebates_loop(self):
        """THE load-bearing measurement: does the maker rebate actually credit?
        Modelled as 0.2·0.07·p(1−p) = 0.35 c/sh at p=0.5 (venue feeSchedule
        rebateRate=0.2, makerRebatesFeeShareBps=10000). If this reads ~0 while
        we are filling as maker, every maker strategy on this venue is dead."""
        import json
        import urllib.request
        from config import POLYMARKET_FUNDER
        while True:
            await asyncio.sleep(900.0)
            try:
                d = time.strftime("%Y-%m-%d", time.gmtime())
                url = (f"https://clob.polymarket.com/rebates/current?date={d}"
                       f"&maker_address={POLYMARKET_FUNDER}")
                r = json.loads(urllib.request.urlopen(url, timeout=20).read())
                tot = 0.0
                if isinstance(r, list):
                    tot = sum(float(x.get("rebated_fees_usdc") or 0) for x in r)
                _event("PF_OM_REBATES", date=d, total=round(tot, 5),
                       fills=self.n_fills)
            except Exception:
                pass

    async def hb_loop(self):
        while True:
            await asyncio.sleep(120.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _event("PF_OM_HB", quotes=len(self.quotes), fills=self.n_fills,
                   placed=self.n_quotes, rejected=self.n_rejected,
                   inv=round(sum(self.inv.values()), 1),
                   day_pnl=round(self.day_pnl.get(day, 0.0), 3),
                   halted=self.halted, live=_real)

    async def run(self):
        log.info("openmm %s %s size=%.0f band=[%.2f,%.2f] tl=[%.0f,%.0f] "
                 "imb>=%.2f fv=%.2f pull=%.2fbps/%.1fs",
                 "LIVE" if _real else "PAPER", COIN, SIZE, BAND_LO, BAND_HI,
                 TL_LO, TL_HI, IMB_THR, FV_THR, PULL_BPS, PULL_WIN)
        _event("PF_OM_START", live=_real, size=SIZE, band_lo=BAND_LO,
               band_hi=BAND_HI, tl_lo=TL_LO, tl_hi=TL_HI, imb=IMB_THR,
               fv=FV_THR, pull_bps=PULL_BPS, max_daily_loss=LIVE_MAX_DAILY_LOSS_USD)
        if _real:
            from engine.clob import (build_clob_client, ensure_approvals,
                                     fetch_usdc_balance)
            self.clob = await asyncio.to_thread(build_clob_client)
            await asyncio.to_thread(ensure_approvals, self.clob)
            bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
            _event("PF_OM_READY", balance=bal)
            log.info("openmm LIVE ready balance=$%.2f", bal or -1)
        await asyncio.gather(run_pm_ws(), run_binance_ws(), self.farm_loop(),
                             self.hb_loop(), self.resolve_loop(),
                             self.rebates_loop())


def main():
    asyncio.run(OpenMM().run())


if __name__ == "__main__":
    main()
