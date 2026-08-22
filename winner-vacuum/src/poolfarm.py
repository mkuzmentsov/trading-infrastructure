"""poolfarm — farm the $1M/month crypto liquidity-rewards pools (live 2026-08-11).

Program (docs/programs/liquidity-rewards, verified via CLOB rewards API):
per-series daily pools (btc-5m $10k/day; eth/sol/xrp $1,667; doge/bnb $833),
paid daily at 00:00 UTC to makers resting >= min_size (50sh) within
max_spread (1.5c) of the adjusted mid, sampled once per random minute.
Two "sides" = (bid UP == ask DOWN) and (ask UP == bid DOWN); single-sided
scores 1/3 while mid in [0.10, 0.90] and ZERO outside. Orders must rest
>= 3.5s. Day-1 competitiveness ~0 -> early share of the pool is the prize.

Strategy: BUY UP and BUY DOWN (two-sided, USDC-only) at the FAR edge of the
qualifying band (mid -/+ ~1.5c, tick-rounded inward) to minimize fills while
scoring. Re-center only on >= RECENTER_C drift and never before MIN_REST.
Stand down when the mid leaves [MID_LO, MID_HI] or inside the final QUIT_TL
seconds (pinned books = pure adverse selection, and the program pays zero
single-sided there anyway). On a fill: quote the acquired token back out
post-only at +EXIT_TICKS above entry (restores two-sidedness AND exits
inventory); unresolved inventory rides to redemption via the sweeper.

Env: PM_MM_SIZE(50) PM_MM_EDGE_C(1.5) PM_MM_RECENTER_C(1.0) PM_MM_MIN_REST(4)
     PM_MM_MID_LO(0.12) PM_MM_MID_HI(0.88) PM_MM_QUIT_TL(45) PM_MM_WARMUP(4)
     PM_MM_EXIT_TICKS(2) PM_MM_MAX_INV_SH(150) LIVE_MAX_DAILY_LOSS_USD halt.
"""
from __future__ import annotations

import asyncio
import math
import os
import time

from config import (BAR_SECONDS, DRY_RUN, LIVE_MAX_DAILY_LOSS_USD,
                    LIVE_TRADING, TRAINING_EVENT_LOG_PATH, log)
from core.gamma import grid_window_start
from core.pm_ws import pm_state, run_pm_ws
from execution.events import EventLog

COIN = os.getenv("COIN", "btc").lower()
_real = LIVE_TRADING and not DRY_RUN

SIZE = float(os.getenv("PM_MM_SIZE", "50"))
EDGE_C = float(os.getenv("PM_MM_EDGE_C", "1.5")) / 100.0
RECENTER_C = float(os.getenv("PM_MM_RECENTER_C", "1.0")) / 100.0
MIN_REST = float(os.getenv("PM_MM_MIN_REST", "4"))
MID_LO = float(os.getenv("PM_MM_MID_LO", "0.12"))
MID_HI = float(os.getenv("PM_MM_MID_HI", "0.88"))
QUIT_TL = float(os.getenv("PM_MM_QUIT_TL", "45"))
WARMUP = float(os.getenv("PM_MM_WARMUP", "4"))
EXIT_TICKS = int(os.getenv("PM_MM_EXIT_TICKS", "2"))
MAX_INV_SH = float(os.getenv("PM_MM_MAX_INV_SH", "150"))
# PAIR-COST CEILING: once one leg fills at p, the opposite leg is capped at
# (PAIR_CEIL - p) so any COMPLETED pair is guaranteed to cost < 1.00. Without
# it, a whipsawing bar fills UP@0.72 early and DOWN@0.57 late (each below its
# OWN mid at the time) for a 1.29 pair = guaranteed loss (live 2026-08-12,
# bar 1, -$14.50). If the mid won't let the second leg bid that low it simply
# does not fill and we stay one-sided on the below-mid first leg.
PAIR_CEIL = float(os.getenv("PM_MM_PAIR_CEIL", "0.985"))
# BATCH quoting (2026-08-13, user idea): build the 50/50 pair in BATCH-share
# maker increments with an imbalance throttle — quote a side only while its
# held shares don't exceed the other side's by >= BATCH. Max unhedged exposure
# at any moment ~= one batch instead of the full SIZE (1h backtest: worst bar
# -$29 @ 50 -> -$10 @ 10 -> -$4 @ 5; matched volume shrinks with batch, 10 is
# the compromise). BATCH = SIZE (default) reproduces the plain one-shot pair.
BATCH_SH = float(os.getenv("PM_MM_BATCH_SH", str(SIZE)))
# v2: NO-CHASE. Quote each side ONCE per bar at the far edge of the reward
# band; never re-center to follow the mid. Chasing was 54% of the -$111
# loss (2026-08-11: 17 high-churn bars, pair cost 1.063). If the mid runs
# so our resting quote leaves the reward band, just CANCEL and sit out the
# rest of the bar rather than re-quote higher. VOL_PULL cancels both sides
# when the mid jumps >VOL_PULL in one tick (a directional move = toxic).
NO_CHASE = os.getenv("PM_MM_NO_CHASE", "true").lower() in ("true","1","yes")
VOL_PULL = float(os.getenv("PM_MM_VOL_PULL_C", "1.5")) / 100.0

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


class Quote:
    __slots__ = ("oid", "token", "side", "px", "sh", "placed", "role")

    def __init__(self, oid, token, side, px, sh, role):
        self.oid = oid
        self.token = token
        self.side = side
        self.px = px
        self.sh = sh
        self.placed = time.time()
        self.role = role                    # "up" | "down" | "exit"


class PoolFarm:
    def __init__(self):
        self.clob = None
        self.side_cool: dict[str, float] = {}   # role -> no-requote-until ts
        self.bar_fills: dict[tuple, int] = {}   # (ws, role) -> fills this bar
        self.bar_leg_px: dict[tuple, float] = {}   # (ws, role) -> our fill px
        self.quotes: dict[str, Quote] = {}
        self.inv: dict[str, float] = {}     # token -> shares held (fills)
        self.inv_cost: dict[str, float] = {}
        self.day_pnl: dict[str, float] = {}
        self.halted = False
        self.n_quotes = 0
        self.n_fills = 0
        self.bar_quoted: dict[tuple, bool] = {}   # (ws, role) -> quoted this bar
        self.bar_pulled: dict[int, bool] = {}     # ws -> pulled (sit out)
        self.last_mid = None

    # ── helpers ─────────────────────────────────────────────────────────────
    def _mid(self):
        if not pm_state.ready:
            return None
        ub, ua = pm_state.up_bid, pm_state.up_ask
        if not (0 < ub < 1 and 0 < ua < 1) or ua < ub:
            return None
        return (ub + ua) / 2.0

    def _edge_px(self, mid: float, side: str):
        """Deepest qualifying tick: within EDGE_C of mid, rounded inward."""
        # round AWAY from mid (cheaper buy / richer sell) while staying inside
        # the reward band -> fewer, cheaper fills.
        if side == "buy":
            return math.floor((mid - EDGE_C) * 100 + 1e-9) / 100.0
        return math.ceil((mid + EDGE_C) * 100 - 1e-9) / 100.0

    async def _cancel(self, q: Quote, reason: str):
        from engine.clob import cancel_order
        ok = True
        if _real and q.oid:
            ok = await asyncio.to_thread(cancel_order, self.clob, q.oid)
        self.quotes.pop(q.oid or f"paper-{id(q)}", None)
        _event("PF_MM_CANCEL", oid=(q.oid or "")[:16], role=q.role,
               px=q.px, reason=reason, ok=ok)

    async def _place(self, token: str, px: float, sh: float, role: str,
                     side: str = "BUY"):
        from engine.clob import place_limit_order
        if not (0.01 <= px <= 0.99):
            return
        oid = None
        if _real:
            try:
                oid = await asyncio.to_thread(
                    place_limit_order, self.clob, token, side, sh, px)
            except Exception as exc:
                _event("PF_MM_ERR", where="place", err=str(exc)[:140])
                return
            if not oid:
                return
        q = Quote(oid, token, side, px, sh, role)
        self.quotes[oid or f"paper-{id(q)}"] = q
        self.n_quotes += 1
        _event("PF_MM_QUOTE", oid=(oid or "paper")[:16], role=role, side=side,
               px=px, sh=sh, live=_real)

    async def _check_fills(self):
        """Poll open quotes; on a (partial) fill, book inventory and place the
        recovery exit quote."""
        from engine.clob import fetch_order_status
        for key, q in list(self.quotes.items()):
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
            if matched > 0 and status in ("matched", "filled") or \
                    (matched >= q.sh - 1e-6):
                self.quotes.pop(key, None)
                self.n_fills += 1
                day = time.strftime("%Y-%m-%d", time.gmtime())
                if q.side == "SELL":
                    held = self.inv.get(q.token, 0.0)
                    cost = self.inv_cost.get(q.token, 0.0)
                    avg = cost / held if held > 1e-9 else 0.0
                    take = min(matched, held)
                    self.inv[q.token] = held - take
                    self.inv_cost[q.token] = max(0.0, cost - avg * take)
                    pnl = take * (q.px - avg)
                    self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                    _event("PF_MM_FILL", oid=q.oid[:16], role=q.role, px=q.px,
                           sh=matched, side="SELL", pnl=round(pnl, 4))
                    continue
                self.inv[q.token] = self.inv.get(q.token, 0) + matched
                self.inv_cost[q.token] = (self.inv_cost.get(q.token, 0)
                                          + matched * q.px)
                # DISCIPLINE (2026-08-12): HOLD to redemption. NO exit sell,
                # NO partner-cancel. Live diagnosis: every fill was placed
                # BELOW mid, so it is +EV held to $1 (paid < fair). Exit
                # round-trips and partner-cancel converted these neutral +EV
                # holds into bad one-sided directional bets (up@0.87 etc) —
                # 96% of the -$111 loss. Just hold; the resolve loop books it.
                self.side_cool[q.role] = time.time() + 30.0
                ws_now = grid_window_start(time.time())
                k = (ws_now, q.role)
                self.bar_fills[k] = self.bar_fills.get(k, 0) + 1
                self.bar_leg_px[k] = q.px       # for the pair-cost ceiling
                if len(self.bar_fills) > 64:
                    self.bar_fills = {kk: v for kk, v in
                                      self.bar_fills.items()
                                      if kk[0] >= ws_now - 3600}
                    self.bar_leg_px = {kk: v for kk, v in
                                       self.bar_leg_px.items()
                                       if kk[0] >= ws_now - 3600}
                _event("PF_MM_FILL", oid=q.oid[:16], role=q.role, px=q.px,
                       sh=matched, side="BUY")
                # HOLD to redemption — no exit quote (see discipline note above).
            elif status in ("cancelled", "canceled"):
                self.quotes.pop(key, None)

    # ── main loop ───────────────────────────────────────────────────────────
    async def farm_loop(self):
        while True:
            await asyncio.sleep(1.0)
            try:
                await self._tick()
            except Exception as exc:
                log.exception("farm: %s", exc)
                _event("PF_MM_ERR", where="tick", err=str(exc)[:140])

    async def _tick(self):
        now = time.time()
        ws = grid_window_start(now)
        end = ws + BAR_SECONDS
        tl = end - now
        day = time.strftime("%Y-%m-%d", time.gmtime())
        # STICKY per-UTC-day latch: once halted, stay halted for the whole day
        # regardless of later PnL wiggles. Bug 2026-08-12 04:44: a post-halt
        # resolve pushed day_pnl back above -25, `_halt_since` reset to 0, and
        # the next tick re-quoted 70s after the halt. The latched day is the
        # only authority; day_pnl only ARMS it.
        if getattr(self, "_halt_day", None) == day:
            for q in list(self.quotes.values()):
                await self._cancel(q, "halt")
            return
        if self.day_pnl.get(day, 0.0) <= -LIVE_MAX_DAILY_LOSS_USD:
            # let paired resolves land before latching (a pair's loss leg
            # booked 1s before its win leg false-triggered this on 08-11)
            if not getattr(self, "_halt_since", 0):
                self._halt_since = now
            if now - self._halt_since < 6.0:
                return
            if self.day_pnl.get(day, 0.0) > -LIVE_MAX_DAILY_LOSS_USD:
                self._halt_since = 0     # recovered inside the window: no halt
                return
            self.halted = True
            self._halt_day = day
            _event("PF_MM_HALT", day=day,
                   day_pnl=round(self.day_pnl.get(day, 0.0), 2))
            for q in list(self.quotes.values()):
                await self._cancel(q, "halt")
            return
        self._halt_since = 0
        mid = self._mid()
        in_window = (pm_state.market_end_ts == end and WARMUP < (now - ws)
                     and tl > QUIT_TL and mid is not None
                     and MID_LO <= mid <= MID_HI
                     and sum(self.inv.values()) < MAX_INV_SH)
        core = [q for q in self.quotes.values() if q.role in ("up", "down")]
        if not in_window:
            for q in core:
                await self._cancel(q, "window")
            return
        await self._check_fills()
        # desired: BUY UP at edge below up-mid, BUY DOWN at edge below dn-mid
        want = {
            "up": (pm_state.token_id_up, self._edge_px(mid, "buy")),
            "down": (pm_state.token_id_down, self._edge_px(1.0 - mid, "buy")),
        }
        # (vol-pull removed 2026-08-12: it fired on nearly every tick of these
        # thin swinging books and blocked ALL quoting. The hold-to-redemption
        # + never-above-mid discipline is the protection; a directional move
        # just deepens our resting bid, which is fine.)
        self.last_mid = mid
        tok_up, tok_dn = pm_state.token_id_up, pm_state.token_id_down
        inv_up = self.inv.get(tok_up, 0.0) if tok_up else 0.0
        inv_dn = self.inv.get(tok_dn, 0.0) if tok_dn else 0.0
        for role, (token, px) in want.items():
            if not token:
                continue
            m = mid if role == "up" else 1.0 - mid
            cur = next((q for q in self.quotes.values() if q.role == role), None)
            mine = inv_up if role == "up" else inv_dn
            theirs = inv_dn if role == "up" else inv_up
            # HARD PER-SIDE CAP (2026-08-13 fix): never HOLD more than SIZE of one
            # side per bar. Checked UNCONDITIONALLY here, because the bar_fills
            # guard below is only reached when cur is None — the reband path
            # `continue`s past it, so on a fast down-dump our DOWN bid refilled 3×
            # to 150sh = a -$53 directional blow + the collateral drain that
            # storm-failed every order. self.inv is the REAL held shares (updated
            # on every fill), so this holds regardless of the fill-detect timing.
            if mine >= SIZE - 1e-6:
                if cur is not None:
                    await self._cancel(cur, "side_cap")
                continue
            # BATCH IMBALANCE THROTTLE (2026-08-13): while this side is ahead of
            # the other by >= one batch, stand down and let the lagging side
            # catch up. Caps unhedged exposure at ~BATCH shares at any moment
            # (BATCH == SIZE -> never fires -> plain one-shot pair).
            if mine - theirs >= BATCH_SH - 1e-6:
                if cur is not None:
                    await self._cancel(cur, "imbalance")
                continue
            # PAIR-COST CEILING: once the opposite leg has filled this bar, this
            # leg may only complete the pair at a price that keeps the pair
            # < PAIR_CEIL. Ceiling is on the opposite side's AVG cost so the
            # CUMULATIVE pair stays locked as batches accumulate. `cap` is the
            # deepest such price (None = free to quote at edge). On a whipsaw
            # this deepens or suppresses the 2nd leg so we can never buy both
            # sides near their local highs for a >1.00 pair.
            other = "down" if role == "up" else "up"
            tok_other = tok_dn if role == "up" else tok_up
            cap = None
            if theirs > 1e-6 and tok_other:
                avg_other = self.inv_cost.get(tok_other, 0.0) / theirs
                cap = math.floor((PAIR_CEIL - avg_other) * 100 + 1e-9) / 100.0
            # A STANDING bid that violates the ceiling (opposite filled AFTER we
            # placed it) is toxic — it would complete a >1.00 pair. Cancel it
            # NOW, no MIN_REST wait; next tick re-places deep (or not at all).
            if cur is not None and cap is not None and cur.px > cap:
                await self._cancel(cur, "pair_ceil")
                continue
            if cap is not None:
                if cap < 0.01:          # cannot complete a profitable pair
                    if cur is not None:
                        await self._cancel(cur, "pair_ceil")
                    continue
                if px > cap:
                    px = cap            # deepen the bid to lock the pair
            # HARD GUARD: never rest a bid at/above this side's mid. Every fill
            # must be below fair value so holding to redemption is +EV. `px`
            # (floor(m-EDGE)) already is, but guard against rounding/edge=0.
            if px >= m - 0.004:
                if cur is not None:
                    await self._cancel(cur, "above_mid")
                continue
            if cur is not None:
                # re-quote to follow the mid ONLY when the standing bid left the
                # reward band (>1.5c from mid) — it is no longer scoring. The
                # replacement is still floor(m-EDGE), i.e. BELOW the new mid, so
                # we never chase UP into a fill. Never before MIN_REST (>=3.5s
                # eligibility).
                if (m - cur.px > EDGE_C + 0.006 or cur.px >= m - 0.004) and \
                        now - cur.placed >= MIN_REST:
                    await self._cancel(cur, "reband")
                continue
            # (one-fill-per-side burst guard removed 2026-08-13: superseded by
            # the inventory-based side cap + batch imbalance throttle above —
            # with batches we WANT multiple fills per side, throttled by real
            # held shares, not a fill counter.)
            sh = min(BATCH_SH, SIZE - mine)
            if sh * px < 1.05 and px > 0:      # venue min order $1
                sh = min(SIZE - mine, math.ceil(1.05 / px))
            if sh < 5:                          # venue min 5 shares
                continue
            await self._place(token, px, sh, role)

    async def resolve_loop(self):
        """Inventory from ENDED bars: look up the outcome and realize pnl
        (the sweeper redeems winners on-chain; losers are written off), so
        the inventory cap frees and the daily halt sees the truth."""
        import json as _json
        import urllib.request as _rq
        from core.gamma import window_slug
        pending: dict[str, tuple[int, float, float]] = {}
        known: dict[str, int] = {}
        while True:
            await asyncio.sleep(20.0)
            # map tokens -> bar ws while the market is current
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
                    continue                     # still the live market
                if token not in pending:
                    pending[token] = (ws, sh, self.inv_cost.get(token, 0.0))
                ws, sh, cost = pending[token]
                try:
                    url = ("https://gamma-api.polymarket.com/markets?slug="
                           + window_slug(ws) + "&closed=true")
                    req = _rq.Request(url, headers={"User-Agent": "poolfarm"})
                    d = _json.loads(_rq.urlopen(req, timeout=10).read())
                except Exception:
                    continue
                if not d or not d[0].get("closed"):
                    continue
                op = d[0]["outcomePrices"]
                op = _json.loads(op) if isinstance(op, str) else op
                up_won = str(op[0]) in ("1", "1.0")
                # which token was UP? clobTokenIds order = [up, down]
                try:
                    toks = _json.loads(d[0]["clobTokenIds"])
                except Exception:
                    toks = []
                won = (token == toks[0]) == up_won if toks else False
                pnl = sh * 1.0 - cost if won else -cost
                day = time.strftime("%Y-%m-%d", time.gmtime())
                self.day_pnl[day] = self.day_pnl.get(day, 0.0) + pnl
                self.inv.pop(token, None)
                self.inv_cost.pop(token, None)
                pending.pop(token, None)
                # cancel any stale exit quote on this token
                for q in [q for q in self.quotes.values() if q.token == token]:
                    await self._cancel(q, "resolved")
                _event("PF_MM_RESOLVE", bar=ws, won=won, sh=round(sh, 1),
                       cost=round(cost, 2), pnl=round(pnl, 4),
                       day_pnl=round(self.day_pnl.get(day, 0.0), 3))

    async def reconcile_loop(self):
        """VENUE-TRUTH inventory reconcile (added 2026-08-20 after a live cap
        breach). The hard per-side cap keys off self.inv, which is only updated
        by _check_fills' order polling — so any fill we FAIL to detect leaves
        inv stale and the cap silently disarmed. Live 2026-08-20 14:00 ET bar:
        4 down fills (19 shares) during a fast dump went undetected, inv stayed
        at 10, and the bot bought 29 shares on one side against a SIZE=10 cap,
        leaving a 19-share unhedged directional bet.

        This only ever RAISES inv toward what the venue says we hold, never
        lowers it, so it can only make the cap MORE restrictive — it cannot
        cause new orders. Fail-safe by construction.
        """
        import json as _json
        import urllib.request as _rq
        from config import POLYMARKET_FUNDER
        # 5s, not 25s: the cap is `sh = min(BATCH_SH, SIZE - mine)`, which is
        # correct only while `mine` is fresh. Live 2026-08-20 both breaches were
        # stale-inventory, not bad arithmetic — fills 22-33s apart outran a 25s
        # reconcile, so a 3rd batch went out against an already-full side
        # (5PM: 15/15, benign+paired; 2PM: 29/10, a 19-share unhedged bet).
        # This loop only ever RAISES inv, so a faster tick can only make the cap
        # STRICTER — it can never cause an order.
        # 15s, not 5s: at 5s TWO bots hammered data-api into HTTP 429
        # (2026-08-20 21:49), the reconcile failed intermittently, inventory
        # went stale anyway and eth drifted to inv=45 against a 30 cap. Backs
        # off hard on 429 so a rate-limit storm cannot silently disarm the cap.
        # 30s base, STAGGERED per coin. Both bots egress from one cluster IP, so
        # they compete for the same data-api limit: at 15s each, eth logged 11
        # consecutive 429s and ZERO successful reconciles (2026-08-20 22:xx) —
        # its guard was inert again. Offsetting by half the interval stops the
        # two from colliding every tick.
        delay = 30.0
        await asyncio.sleep((hash(COIN) % 2) * 15.0)
        while True:
            await asyncio.sleep(delay)
            try:
                toks = {t for t in (pm_state.token_id_up, pm_state.token_id_down) if t}
                if not toks:
                    continue
                # ⚠️ MUST filter to redeemable=false. The plain positions
                # query returns at most 100 rows and THIS VAULT IS SATURATED by
                # 100+ ancient worthless rows (sz=248 @ 2c), so our live
                # positions never appear and the reconcile silently no-ops —
                # verified inert 2026-08-20 ("100 rows, 0 matching current
                # bar"). Same endpoint trap that produced a false -$28.50
                # alarm earlier the same day. redeemable=false returns ~4 rows.
                # Prefer the MARKET-FILTERED query: 2 rows instead of 4 and
                # the cheapest call available. Both bots share one egress IP,
                # so every saved request matters (btc hit 12x 429 at 07:10).
                # Falls back to the redeemable filter if the condition id is
                # not known yet. NEVER use the unfiltered query: it caps at 100
                # rows and this vault is saturated by dead ones (see above).
                cid = getattr(pm_state, "condition_id", None)
                if cid:
                    url = ("https://data-api.polymarket.com/positions?user="
                           + str(POLYMARKET_FUNDER) + "&market=" + str(cid))
                else:
                    url = ("https://data-api.polymarket.com/positions?user="
                           + str(POLYMARKET_FUNDER)
                           + "&redeemable=false&sizeThreshold=0.01&limit=100")
                req = _rq.Request(url, headers={"User-Agent": "poolfarm"})
                rows = _json.loads(_rq.urlopen(req, timeout=15).read())
                for r in rows:
                    a = str(r.get("asset") or r.get("asset_id") or "")
                    if a not in toks:
                        continue
                    real = float(r.get("size") or 0)
                    held = self.inv.get(a, 0.0)
                    if real > held + 1e-6:
                        px = float(r.get("avgPrice") or 0) or None
                        self.inv[a] = real
                        if px:
                            self.inv_cost[a] = real * px
                        _event("PF_MM_RECONCILE", token=a[:14],
                               was=round(held, 2), now=round(real, 2),
                               added=round(real - held, 2))
                delay = 30.0                      # healthy: back to normal
            except Exception as exc:
                msg = str(exc)[:140]
                if "429" in msg:
                    delay = min(120.0, delay * 2)  # rate limited: back off
                _event("PF_MM_ERR", where="reconcile", err=msg,
                       next_s=round(delay, 1))

    async def hb_loop(self):
        while True:
            await asyncio.sleep(120.0)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            _event("PF_MM_HB", quotes=len(self.quotes), fills=self.n_fills,
                   placed=self.n_quotes, inv=round(sum(self.inv.values()), 1),
                   day_pnl=round(self.day_pnl.get(day, 0.0), 2),
                   halted=self.halted, live=_real)

    async def rewards_loop(self):
        """Daily-ish visibility: the no-auth rebates endpoint for our maker
        address (rewards themselves appear in the CLOB user endpoints /
        next-day MCP pull)."""
        import json
        import urllib.request
        from config import POLYMARKET_FUNDER
        while True:
            await asyncio.sleep(1800.0)
            try:
                d = time.strftime("%Y-%m-%d", time.gmtime())
                url = (f"https://clob.polymarket.com/rebates/current?date={d}"
                       f"&maker_address={POLYMARKET_FUNDER}")
                r = json.loads(urllib.request.urlopen(url, timeout=20).read())
                tot = 0.0
                if isinstance(r, list):
                    tot = sum(float(x.get("rebated_fees_usdc") or 0) for x in r)
                _event("PF_MM_REBATES", date=d, total=round(tot, 4))
            except Exception:
                pass

    async def run(self):
        log.info("poolfarm %s %s size=%.0f edge=%.1fc window=[%.2f,%.2f] "
                 "quit_tl=%.0f", "LIVE" if _real else "PAPER", COIN, SIZE,
                 EDGE_C * 100, MID_LO, MID_HI, QUIT_TL)
        _event("PF_MM_START", live=_real, size=SIZE, edge_c=EDGE_C * 100,
               quit_tl=QUIT_TL)
        if _real:
            from engine.clob import (build_clob_client, ensure_approvals,
                                     fetch_usdc_balance)
            self.clob = await asyncio.to_thread(build_clob_client)
            await asyncio.to_thread(ensure_approvals, self.clob)
            bal = await asyncio.to_thread(fetch_usdc_balance, self.clob)
            _event("PF_MM_READY", balance=bal)
            log.info("poolfarm LIVE ready balance=$%.2f", bal or -1)
        await asyncio.gather(run_pm_ws(), self.farm_loop(), self.hb_loop(),
                             self.resolve_loop(), self.rewards_loop(),
                             self.reconcile_loop())


def main():
    asyncio.run(PoolFarm().run())


if __name__ == "__main__":
    main()
