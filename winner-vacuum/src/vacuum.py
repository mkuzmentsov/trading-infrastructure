"""vacuum.py — POST-CLOSE 99c winner vacuum (GTC RESTING).

Edge (validated 2026-07-25 from wallet 0xA7614974…: 172 btc bars, 100% WR,
+$26.5k/115d; our tape shows ~$8.5/bar avg supply on btc, 21% of bars >100sh):
after bar-close the outcome is decided, but holders of the WINNING token keep
dumping at 0.955-0.999 to free capital instantly instead of waiting minutes for
redemption. Buying those sells and redeeming at $1.00 is near-riskless — the
only risk is a wrong winner-lock, which the |lead| gate keeps rare and the
per-deal notional keeps bounded.

Mechanics (same GTC-REST rationale as settlement-sniper/snipe.py): one
presigned GTC buy at CAP(0.99) on the locked winner posted right at close; it
rests on the book and the venue matches every sell that crosses ≤CAP during
the window server-side (zero per-fill latency). Any resting asks below CAP at
placement fill immediately at THEIR price (even cheaper). Cancel remainder at
window end; hold fills to settlement.

Differences vs the ≤5c sniper:
  - CAP 0.99 (the supply lives at 0.955-0.999, not at 1-5c),
  - longer window (fills cluster +1..+9s; default 20s),
  - MIN_LEAD 8bps mandatory (a mislock costs ~CAP per share here, not 5c),
  - meaningful notional (edge is ~1c/share; $5 deals would be pointless).

Env (same keys as sniper so the chart templates work unchanged):
  SNIPE_CAP(0.99) SNIPE_FIRE_MAX_SECS(20) SNIPE_NOTIONAL(100)
  SNIPE_MIN_LEAD_BPS(8) SNIPE_MAX_DAILY_LOSS(100). FAV_ORDER_TYPE must be
  'gtc'. Runner needs POST_CLOSE_GRACE_SECS >= FIRE_MAX + slack (e.g. 25).
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

CAP = float(os.getenv("SNIPE_CAP", "0.99"))
FIRE_MAX = float(os.getenv("SNIPE_FIRE_MAX_SECS", "20"))
NOTIONAL = float(os.getenv("SNIPE_NOTIONAL", "100"))
MIN_LEAD_BPS = float(os.getenv("SNIPE_MIN_LEAD_BPS", "8"))
MAX_DAILY_LOSS = float(os.getenv("SNIPE_MAX_DAILY_LOSS", "100"))
# v2 state-lock: below the lead gate, lock the winner from POST-CLOSE PRINTS —
# the first token trading rich with real size is the winner being bought by
# informed flow (mirrors the source wallet, which trades nearly every bar)
CONFIRM_WAIT = float(os.getenv("VAC_CONFIRM_WAIT_SECS", "6"))
CONFIRM_PX = float(os.getenv("VAC_CONFIRM_PX", "0.90"))
CONFIRM_SH = float(os.getenv("VAC_CONFIRM_MIN_SH", "100"))
CONFIRM_MIN_ELAPSED = float(os.getenv("VAC_CONFIRM_MIN_ELAPSED", "2.0"))
PRINT_CAP = float(os.getenv("VAC_PRINT_CAP", "0.93"))
# v3 pre-close queue entry: the 0.99 bid queue is FIFO per price level and the
# post-close absorber (0xA7614974) only places AFTER close — resting our GTC a
# couple seconds BEFORE close on decided bars puts us ahead of it for the
# entire post-close capital-freeing flow. Gate per coin at the 0-flip lead
# threshold measured on mrec (btc/eth/sol 5bps, doge 8, bnb 10, xrp 15); a
# watchdog cancels if the lead decays before close. 0 disables.
PRE_LEAD_BPS = float(os.getenv("VAC_PRE_LEAD_BPS", "0"))
PRE_PLACE_SECS = float(os.getenv("VAC_PRE_PLACE_SECS", "2.0"))
PRE_CANCEL_BPS = float(os.getenv("VAC_PRE_CANCEL_BPS", "2.0"))
# early tier: join the 0.99 FIFO well before close on STRONG leads — the 0.99
# level queue forms minutes early (BoneOhio-style ladders) and t-2s joins sit
# behind it. btc mrec backtest (t<=45s arm, watchdog sim): >=8bps -> 93 armed,
# 3 canceled, 0 flips held. May cross the book mid-bar at <=0.99 — that's the
# same trade at a better price per the flip table. 0 disables.
EARLY_LEAD_BPS = float(os.getenv("VAC_EARLY_LEAD_BPS", "0"))
EARLY_PLACE_SECS = float(os.getenv("VAC_EARLY_PLACE_SECS", "45"))
# fine-tick price jump: matching inside a price level is effectively
# size-weighted (0.04-0.9M-share bluff walls at 0.99; our $40 captured 0 of
# $6.8k printed flow on 2026-07-27 quiet hours) — but PRICE priority beats
# size, and tick flips 0.01->0.001 once the book crosses 0.96 (~40s
# pre-close). Bidding FINE_PX (0.995) tops the whole 0.99 wall at 0.5%/share
# margin. Try fine first near/after close, fall back to CAP when the tick is
# still coarse. 0 disables.
FINE_PX = float(os.getenv("VAC_FINE_PX", "0"))
# abort-salvage: after a watchdog cancel, FAK-sell already-filled shares if
# the book still bids >= this floor (0 disables; exits ~fair on a coin-flip)
SALVAGE_FLOOR = float(os.getenv("VAC_SALVAGE_FLOOR", "0.50"))
# v3.5 MAKER mode (separate deployment): rest a bid at MAKER_PX on the leading
# side once the book itself prices it above us (ask > MAKER_PX) inside the
# last MAKER_SECS of the bar, and hold through the post-close window. Sellers
# de-risking a near-decided bar cross into us; margin is (1-MAKER_PX)/share.
# Validated live by wallet 0x5f02d66c… ("moneymaker748": 482 btc bars/48h at
# 0.98, 98.8% WR, +$1.2k) and on mrec (btc 900 bars: 463W/1 flip/26 salvaged,
# +$0.42/bar/100sh, positive each day; watchdog+salvage beats hold by $426).
# The book condition IS the gate — no lead threshold needed beyond sign.
MODE = os.getenv("VAC_MODE", "snipe").lower()
MAKER_PX = float(os.getenv("VAC_MAKER_PX", "0.98"))
MAKER_SECS = float(os.getenv("VAC_MAKER_SECS", "120"))

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


class VacuumStrategy:
    def __init__(self) -> None:
        self.runner = None
        self.open_bets: dict[int, dict] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self._last_lead: dict[int, float] = {}   # ws -> last pre-close lead
        self._winner: dict[int, str] = {}        # ws -> "UP"/"DOWN" (locked)
        self._order: dict[int, str] = {}         # ws -> resting order id
        self._lock_src: dict[int, str] = {}      # ws -> "pre"|"lead"|"prints"
        self._pre_placed: set[int] = set()       # bars entered pre-close
        self._pre_aborted: set[int] = set()      # pre-close watchdog cancels
        self._px: dict[int, float] = {}          # ws -> resting price
        self._upgraded: set[int] = set()         # bars re-placed at FINE_PX
        self._imm_fill: dict[int, float] = {}    # ws -> shares filled on placement
        self._imm_px: dict[int, float] = {}      # ws -> avg px of placement cross
        self._done: set[int] = set()
        self.settled: set[int] = set()

    def bind(self, runner) -> None:
        self.runner = runner
        _event("VAC_START", live=_real, mode="gtc_rest", cap=CAP, fire_max=FIRE_MAX,
               notional=NOTIONAL, min_lead_bps=MIN_LEAD_BPS, max_dd=MAX_DAILY_LOSS)

    def presign_requests(self, ctx):
        # presign BOTH sides; at trigger we POST the leader's as GTC
        px = MAKER_PX if MODE == "maker" else CAP
        sz = _shares(NOTIONAL)
        reqs = []
        if ctx.up_token:
            reqs.append(("vac-UP", ctx.up_token, px, sz))
        if ctx.down_token:
            reqs.append(("vac-DOWN", ctx.down_token, px, sz))
        return reqs

    def _print_confirm(self, ws: int):
        """Post-close print signature: cumulative shares traded at >=CONFIRM_PX
        per token since bar close. Returns 'UP'/'DOWN' when one side qualifies."""
        from core.pm_ws import pm_state
        end = ws + 300
        up_sh = dn_sh = 0.0
        for tr in pm_state.recent_trades:
            if tr["ts"] < end or float(tr["price"]) < CONFIRM_PX:
                continue
            if tr["token_id"] == pm_state.token_id_up:
                up_sh += float(tr["size"])
            elif tr["token_id"] == pm_state.token_id_down:
                dn_sh += float(tr["size"])
        if up_sh >= CONFIRM_SH and up_sh > 4 * dn_sh:
            return "UP"
        if dn_sh >= CONFIRM_SH and dn_sh > 4 * up_sh:
            return "DOWN"
        return None

    def _prune(self, ws: int) -> None:
        for d in (self._last_lead, self._winner, self._order, self._imm_fill,
                  self._imm_px, self._lock_src, self._px):
            for k in [k for k in d if k < ws - 3600]:
                d.pop(k, None)
        self._done = {k for k in self._done if k >= ws - 3600}
        self._pre_placed = {k for k in self._pre_placed if k >= ws - 3600}
        self._pre_aborted = {k for k in self._pre_aborted if k >= ws - 3600}
        self._upgraded = {k for k in self._upgraded if k >= ws - 3600}

    async def _salvage(self, ctx, ws: int) -> None:
        """After a watchdog abort, any shares already bought sit on a bar that
        decayed to a near-coin-flip. If the book still prices our side at
        >= SALVAGE_FLOOR, FAK-sell at ~fair instead of riding −0.99/share tail
        (mrec: cancel-path fills are the single biggest EV drag on the early
        tier). Below the floor we hold — no worse than the old behavior."""
        oid = self._order.get(ws)
        if not oid:
            return
        filled = self.runner.exec.ws_filled(oid) if _real else None
        if filled is None:
            filled = await self.runner.exec.poll_filled(oid) or 0.0
        if not filled or filled <= 0:
            return
        win = self._winner.get(ws)
        token = ctx.up_token if win == "UP" else ctx.down_token
        # the FAK sells into the BEST bids first and only walks down to the
        # floor — estimate the exit at the current book bid, not the floor
        # (sol 2026-07-27: booked -14.4 at floor 0.50 for a ~0.97 exit)
        from core.pm_ws import pm_state
        bid = pm_state.up_bid if win == "UP" else pm_state.down_bid
        est_px = max(SALVAGE_FLOOR, bid) if bid is not None else SALVAGE_FLOOR
        sell_oid = matched = None
        for attempt in (1, 2, 3):
            try:
                sell_oid, matched = await self.runner.exec.sell_fak(
                    token, SALVAGE_FLOOR, filled)
                break
            except Exception as exc:
                # a just-matched buy takes a few seconds to credit the
                # conditional tokens on-chain — "not enough balance" right
                # after the fill only means "not credited yet"; wait and retry
                if "not enough balance" in str(exc) and attempt < 3:
                    await asyncio.sleep(4.0)
                    continue
                _event("VAC_SALVAGE_ERR", bar=ws, side=win, err=str(exc)[:120])
                return
        _event("VAC_SALVAGE", bar=ws, side=win, qty=round(filled, 1),
               floor=SALVAGE_FLOOR, est_px=round(est_px, 3), matched=matched,
               order=sell_oid, live=_real)
        if matched:
            # position exited: PnL at the book-bid estimate; keep it out of
            # the hold-to-resolution settle path
            px = self._px.get(ws, CAP)
            pnl = filled * (est_px - px)
            day = time.strftime("%Y-%m-%d", time.gmtime(ws))
            self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
            self.settled.add(ws)
            self.open_bets[ws] = {"side": win, "fill_px": px,
                                  "fill_qty": filled, "order_id": oid,
                                  "verified": True, "salvaged": True}
            _event("VAC_SETTLE", bar=ws, side=win, outcome="SALVAGED",
                   won=False, fill_px=round(px, 4), qty=round(filled, 1),
                   pnl=round(pnl, 3), day_pnl=round(self.day_pnl[day], 2),
                   live=_real)

    async def _upgrade_to_fine(self, ctx, ws: int, tl: float) -> None:
        """Near close: swap an (unfilled) 0.99 rest for the FINE_PX bid —
        price priority beats the size wall; a filled/partial order is kept."""
        oid = self._order.get(ws)
        if not oid:
            self._upgraded.add(ws)
            return
        win = self._winner.get(ws)
        token = ctx.up_token if win == "UP" else ctx.down_token
        from core.pm_ws import pm_state
        if pm_state.tick_size.get(token, 0.01) >= 0.01:
            return           # tick still coarse — keep the 0.99 queue spot,
                             # retry on a later tick until close
        self._upgraded.add(ws)
        filled = self.runner.exec.ws_filled(oid) if _real else None
        if filled is None:
            filled = await self.runner.exec.poll_filled(oid) or 0.0
        if filled and filled > 0:
            return                       # working order — keep the position
        try:
            await self.runner.exec.cancel(oid)
        except Exception:
            pass
        self._order.pop(ws, None)
        await self._place(ctx, ws, CAP, False, -tl, try_fine=True)

    async def _place(self, ctx, ws: int, price_cap: float, use_presigned: bool,
                     tl_after: float, try_fine: bool = False) -> None:
        """Post the GTC bid on the locked winner ONCE (pre- or post-close)."""
        self._order[ws] = None
        win = self._winner[ws]
        token = ctx.up_token if win == "UP" else ctx.down_token
        key = f"vac-{win}"
        placed_px = price_cap
        if try_fine and FINE_PX > 0:
            # fine prices are only valid once THIS token's tick flipped to
            # 0.001 (venue flips it when the token trades past 0.96) — check
            # the WS-tracked tick instead of eating a rejection round-trip
            from core.pm_ws import pm_state
            try_fine = pm_state.tick_size.get(token, 0.01) < 0.01
        if try_fine and FINE_PX > 0:
            # price-priority jump over the 0.99 size wall; the venue rejects
            # it while the tick is still 0.01 -> fall through to the cap path
            try:
                oid, matched, _s, post_ms, avg_px, filled = \
                    await self.runner.exec.fire_direct(
                        token, FINE_PX, _shares(NOTIONAL), tick_size="0.001")
                self._order[ws] = oid
                self._px[ws] = FINE_PX
                self._imm_fill[ws] = filled or 0.0
                self._imm_px[ws] = avg_px if avg_px else None
                _event("VAC_REST", bar=ws, side=win, order=oid or "FAILED",
                       source=self._lock_src.get(ws), px=FINE_PX,
                       imm_fill=round(filled or 0.0, 1),
                       imm_px=None if avg_px is None else round(avg_px, 4),
                       tl_after=round(tl_after, 2), post_ms=round(post_ms, 1),
                       matched=matched, live=_real)
                return
            except Exception as exc:
                _event("VAC_FINE_REJ", bar=ws, side=win, px=FINE_PX,
                       err=str(exc)[:120])
        try:
            if use_presigned and self.runner.exec.has_presigned(key):
                oid, matched, post_ms, avg_px, filled = \
                    await self.runner.exec.fire_presigned(key)
            else:
                oid, matched, _s, post_ms, avg_px, filled = \
                    await self.runner.exec.fire_direct(
                        token, price_cap, _shares(NOTIONAL))
        except Exception as exc:
            _event("VAC_ERR", bar=ws, side=win, err=str(exc)[:160])
            if self._lock_src.get(ws) == "pre":
                # forget the pre-lock so the post-close path gets a clean try
                self._order.pop(ws, None)
                self._winner.pop(ws, None)
                self._lock_src.pop(ws, None)
                self._pre_placed.discard(ws)
            return
        self._order[ws] = oid
        self._px[ws] = placed_px
        self._imm_fill[ws] = filled or 0.0
        self._imm_px[ws] = avg_px if avg_px else None
        _event("VAC_REST", bar=ws, side=win, order=oid or "FAILED",
               source=self._lock_src.get(ws), px=placed_px,
               imm_fill=round(filled or 0.0, 1),
               imm_px=None if avg_px is None else round(avg_px, 4),
               tl_after=round(tl_after, 2), post_ms=round(post_ms, 1),
               matched=matched, live=_real)

    async def _maker_abort(self, ctx, ws: int, lead, tl: float) -> None:
        self._pre_aborted.add(ws)
        oid = self._order.get(ws)
        if oid:
            try:
                await self.runner.exec.cancel(oid)
            except Exception:
                pass
        _event("VAC_PRE_ABORT", bar=ws, side=self._winner.get(ws),
               lead_bps=None if lead is None else round(lead * 1e4, 1),
               spot_age=round(ctx.spot_age, 1), tl=round(tl, 2))
        await self._salvage(ctx, ws)

    async def _maker_tick(self, ctx) -> None:
        """v3.5 book-maker: rest MAKER_PX on the leader while the book prices
        it above us; watchdog-cancel+salvage on decay; hold winners through
        the post-close window for the capital-freeing flow."""
        ws = ctx.ws
        tl = ctx.t_left
        from core.pm_ws import pm_state
        if tl >= 0:
            lead = None
            if ctx.bar_open and ctx.spot > 0 and ctx.spot_age <= 5.0:
                lead = (ctx.spot - ctx.bar_open) / ctx.bar_open
                self._last_lead[ws] = lead
            if self.halted or ws in self._done:
                return
            if ws in self._pre_placed:
                if self._order.get(ws) and ws not in self._pre_aborted:
                    # unlike the t-2s snipe window, the maker rests for up to
                    # ~3min — alt aggTrade gaps of 5-10s are routine there
                    # (sol 2026-07-27: a 5.1s gap salvaged a -11.8bps winner).
                    # Judge on the LAST KNOWN lead; staleness alone only kills
                    # the bid if the feed is properly dead.
                    known = lead if lead is not None else self._last_lead.get(ws)
                    # book collapse = the market repricing a flip FASTER than
                    # the lead decays (btc 2026-07-27: abort at -2.0bps found
                    # the bid already at 0.62; exit cost -0.36/sh). 0.5 is the
                    # pm_state default before the book loads — not a signal.
                    side_now = self._winner.get(ws)
                    bid = (pm_state.up_bid if side_now == "UP"
                           else pm_state.down_bid)
                    # debounce: a single-tick bid flicker <0.90 aborted a
                    # healthy -8.8bps winner (eth 23:09) — require the
                    # collapse to persist 2 consecutive ticks
                    if bid is not None and 0 < bid < 0.90 and bid != 0.5:
                        self._collapse_ct[ws] = self._collapse_ct.get(ws, 0) + 1
                    else:
                        self._collapse_ct[ws] = 0
                    bad = (known is None or ctx.spot_age > 20.0
                           or abs(known) * 1e4 < PRE_CANCEL_BPS
                           or (known > 0) != (side_now == "UP")
                           or self._collapse_ct[ws] >= 2)
                    if bad:
                        await self._maker_abort(ctx, ws, known, tl)
                return
            if (tl > MAKER_SECS or lead is None
                    or abs(lead) * 1e4 < PRE_CANCEL_BPS
                    or ctx.spot_age > 2.0):
                return
            side = "UP" if lead > 0 else "DOWN"
            ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
            if ask is None or ask <= MAKER_PX + 1e-9:
                return          # book not above us yet — a bid at MAKER_PX
                                # would cross; wait until we would rest
            self._winner[ws] = side
            self._lock_src[ws] = "maker"
            self._pre_placed.add(ws)
            _event("VAC_LOCK", bar=ws, winner=side, source="maker",
                   lead_bps=round(lead * 1e4, 1), tl_after=round(-tl, 2))
            await self._place(ctx, ws, MAKER_PX, True, -tl)
            return
        # post-close: ride the resting bid (winner-side sellers keep crossing)
        if ws in self._done:
            return
        if ws not in self._pre_placed or not self._order.get(ws):
            await self._finalize(ws)
            return
        tl_after = -tl
        if ws not in self._pre_aborted:
            lead = self._last_lead.get(ws)
            side = self._winner.get(ws)
            ask = pm_state.up_ask if side == "UP" else pm_state.down_ask
            bad = (lead is None or abs(lead) * 1e4 < PRE_CANCEL_BPS
                   or (lead > 0) != (side == "UP")
                   # book says our side LOST — its ask collapsed to loser
                   # prices and our 0.98 bid is a target; get out now
                   or (ask is not None and ask < 0.90))
            if bad:
                await self._maker_abort(ctx, ws, lead, tl)
                await self._finalize(ws)
                return
        if tl_after > FIRE_MAX:
            await self._finalize(ws)

    async def on_tick(self, ctx) -> None:
        if MODE == "maker":
            return await self._maker_tick(ctx)
        ws = ctx.ws
        tl = ctx.t_left

        # ── PRE-CLOSE: cache the lead; v3 queue entry near close ─────────────
        if tl >= 0:
            lead = None
            if ctx.bar_open and ctx.spot > 0 and ctx.spot_age <= 5.0:
                lead = (ctx.spot - ctx.bar_open) / ctx.bar_open
                self._last_lead[ws] = lead
            if PRE_LEAD_BPS <= 0 or self.halted or ws in self._done:
                return
            if ws in self._pre_placed:
                # watchdog: kill the resting bid if the lead decays/flips or
                # the spot feed goes stale before close
                oid = self._order.get(ws)
                if oid and ws not in self._pre_aborted:
                    # staleness alone only matters if the feed dies outright:
                    # at a >=gate lead a few blind seconds is inside the
                    # measured 0-flip regime (alt aggTrade gaps 3s+ when quiet)
                    bad = (lead is None or ctx.spot_age > 5.0
                           or abs(lead) * 1e4 < PRE_CANCEL_BPS
                           or (lead > 0) != (self._winner.get(ws) == "UP"))
                    if bad:
                        self._pre_aborted.add(ws)
                        try:
                            await self.runner.exec.cancel(oid)
                        except Exception:
                            pass
                        _event("VAC_PRE_ABORT", bar=ws,
                               side=self._winner.get(ws),
                               lead_bps=None if lead is None else round(lead * 1e4, 1),
                               spot_age=round(ctx.spot_age, 1), tl=round(tl, 2))
                        await self._salvage(ctx, ws)
                    elif (FINE_PX > 0 and tl <= PRE_PLACE_SECS
                          and ws not in self._upgraded):
                        await self._upgrade_to_fine(ctx, ws, tl)
                return
            qualifies = (lead is not None and ctx.spot_age <= 2.0 and (
                (tl <= PRE_PLACE_SECS and abs(lead) * 1e4 >= PRE_LEAD_BPS)
                or (EARLY_LEAD_BPS > 0 and tl <= EARLY_PLACE_SECS
                    and abs(lead) * 1e4 >= EARLY_LEAD_BPS)))
            if qualifies and ws not in self._winner:
                self._winner[ws] = "UP" if lead > 0 else "DOWN"
                self._lock_src[ws] = "pre"
                self._pre_placed.add(ws)
                _event("VAC_LOCK", bar=ws, winner=self._winner[ws], source="pre",
                       lead_bps=round(lead * 1e4, 1), tl_after=round(-tl, 2))
                fine_now = tl <= PRE_PLACE_SECS      # tick is fine only near close
                if fine_now:
                    self._upgraded.add(ws)
                await self._place(ctx, ws, CAP, not fine_now, -tl,
                                  try_fine=fine_now)
            return

        # ── POST-CLOSE window ────────────────────────────────────────────────
        if self.halted or ws in self._done:
            return
        tl_after = -tl

        if tl_after > FIRE_MAX:
            await self._finalize(ws)
            return

        # lock the winner once: decisive spot lead first; else (near-tie) wait
        # for POST-CLOSE PRINT confirmation — first token trading >=CONFIRM_PX
        # with >=CONFIRM_SH cumulative shares is the winner
        if ws not in self._winner:
            lead = self._last_lead.get(ws)
            if lead is not None and abs(lead) * 1e4 >= MIN_LEAD_BPS:
                self._winner[ws] = "UP" if lead > 0 else "DOWN"
                self._lock_src[ws] = "lead"
                _event("VAC_LOCK", bar=ws, winner=self._winner[ws], source="lead",
                       lead_bps=round(lead * 1e4, 1), tl_after=round(tl_after, 2))
            else:
                side = self._print_confirm(ws) if tl_after >= CONFIRM_MIN_ELAPSED else None
                if side is not None:
                    self._winner[ws] = side
                    self._lock_src[ws] = "prints"
                    _event("VAC_LOCK", bar=ws, winner=side, source="prints",
                           lead_bps=None if lead is None else round(lead * 1e4, 1),
                           tl_after=round(tl_after, 2))
                elif tl_after > CONFIRM_WAIT:
                    self._done.add(ws)
                    _event("VAC_SKIP", bar=ws, reason="tie_unconfirmed",
                           lead_bps=None if lead is None else round(lead * 1e4, 1))
                    return
                else:
                    return                    # keep waiting for confirming prints

        # place the resting GTC bid ONCE
        if ws not in self._order:
            printlock = self._lock_src.get(ws) == "prints"
            if printlock:
                # book-sanity: if the "winner's" own ask sits at loser prices
                # the prints were wrong/stale (bnb 2026-07-27: confirm said UP
                # while UP's ask was 0.01 — bid crossed at 1c and lost)
                from core.pm_ws import pm_state
                win = self._winner[ws]
                ask = pm_state.up_ask if win == "UP" else pm_state.down_ask
                if ask is not None and ask < CONFIRM_PX:
                    self._done.add(ws)
                    _event("VAC_SKIP", bar=ws, reason="prints_book_conflict",
                           side=win, ask=ask)
                    return
            # near-tie print-lock: NEVER sweep an uncertain ladder at 0.99 —
            # capped bid only takes sellers who believe it's settled
            await self._place(ctx, ws, PRINT_CAP if printlock else CAP,
                              not printlock, tl_after, try_fine=not printlock)

    async def _finalize(self, ws: int) -> None:
        if ws in self._done:
            return
        self._done.add(ws)
        if ws not in self._winner:
            self._prune(ws)
            return
        oid = self._order.get(ws)
        imm = self._imm_fill.get(ws, 0.0)
        imm_px = self._imm_px.get(ws)
        filled = imm
        if oid:
            # user-WS = real-time fill truth; poll only when the feed is stale
            wsv = self.runner.exec.ws_filled(oid) if _real else None
            if wsv is not None:
                filled = max(filled, wsv)
            else:
                pf = await self.runner.exec.poll_filled(oid)
                if pf is not None:
                    filled = max(filled, pf)
            await self.runner.exec.cancel(oid)
        win = self._winner[ws]
        if filled and filled > 0:
            rest_px = self._px.get(ws, CAP)
            rested = max(0.0, filled - imm)
            cost = imm * (imm_px if imm_px else rest_px) + rested * rest_px
            fill_px = cost / filled
            # PROVISIONAL until settle_loop verifies vs the CLOB trade record
            # (poll_filled fabricates fills for culled orders — 2026-07-25)
            self.open_bets[ws] = {"side": win, "fill_px": fill_px,
                                  "fill_qty": filled, "order_id": oid,
                                  "verified": False}
            _event("VAC_FILL", bar=ws, side=win, filled=round(filled, 1),
                   fill_px=round(fill_px, 4), taker_cross=round(imm, 1),
                   taker_px=None if imm_px is None else round(imm_px, 4),
                   rested_fill=round(rested, 1), order=oid, live=_real)
        else:
            _event("VAC_NOFILL", bar=ws, side=win, order=oid or "FAILED")
        self._prune(ws)

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            now = time.time()
            for ws in [w for w in self.open_bets if w + 300 < now - 8
                       and w not in self.settled]:
                bet = self.open_bets[ws]
                if _real and not bet.get("verified"):
                    v = await self.runner.exec.verified_filled(bet.get("order_id"))
                    if v is None:
                        if now - (ws + 300) < 120:
                            continue           # lookup hiccup — retry
                        v = 0.0
                    if v <= 0:
                        self.settled.add(ws)
                        _event("VAC_PHANTOM", bar=ws, side=bet["side"],
                               polled=round(bet["fill_qty"], 1))
                        continue
                    bet["fill_qty"] = min(bet["fill_qty"], v)
                    bet["verified"] = True
                oc = await asyncio.to_thread(outcome_up, ws)
                if oc is None:
                    if now - (ws + 300) > 600:
                        self.settled.add(ws)
                        _event("VAC_SETTLE_TIMEOUT", bar=ws)
                    continue
                won = (bet["side"] == "UP") == oc
                q = bet["fill_qty"] or 0.0
                pnl = q * ((1.0 if won else 0.0) - bet["fill_px"])
                day = time.strftime("%Y-%m-%d", time.gmtime(ws))
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.settled.add(ws)
                _event("VAC_SETTLE", bar=ws, side=bet["side"],
                       outcome="UP" if oc else "DOWN", won=won,
                       fill_px=round(bet["fill_px"], 4), qty=round(q, 1),
                       pnl=round(pnl, 3), day_pnl=round(self.day_pnl[day], 2),
                       live=_real)
                if self.day_pnl[day] <= -MAX_DAILY_LOSS and not self.halted:
                    self.halted = True
                    _event("VAC_HALT", day=day, day_pnl=round(self.day_pnl[day], 2),
                           max_dd=MAX_DAILY_LOSS)


def main():
    from execution.runner import TakerRunner
    log.info("vacuum %s GTC-REST: coin=%s cap=%.2f fire_max=%.1fs $%.0f/deal "
             "minLead=%.0fbps maxDD=$%.0f", "LIVE" if _real else "PAPER", COIN,
             CAP, FIRE_MAX, NOTIONAL, MIN_LEAD_BPS, MAX_DAILY_LOSS)
    runner = TakerRunner(VacuumStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
