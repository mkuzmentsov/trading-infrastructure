"""mirror_maker — neutral two-sided maker rebate farmer for UpDown 5m bars.

Strategy (per bar):
  - Place MIRRORED maker BUY limits on BOTH tokens around the current mid:
    up_bid = mid_up − OFFSET, down_bid = (1 − mid_up) − OFFSET, so the pair
    cost is ≤ 1 − 2·OFFSET regardless of where the mid sits. Same share count
    both sides → a BOTH-fill locks (1 − pair_cost) × shares profit at
    resolution no matter the outcome (delta-neutral), plus maker rebates.
  - Strict maker guarantee: live orders are GTC **post_only** (the exchange
    rejects any order that would cross/take); paper mirrors that with a
    never-cross price clamp (≤ best_ask − 1 tick).
  - Re-quote both sides when the mid drifts ≥ REQUOTE_CENTS and nothing has
    filled yet (rate-limited). The moment ONE side fills, quoting freezes —
    the opposite quote keeps resting (its fill completes the lock); we never
    chase with takers.
  - At t_left < CUTOFF_SECS: cancel all resting quotes; filled inventory holds
    to resolution (binary settle).
  - Risk: day realized PnL ≤ −MAX_DD → halt new quotes (MM_HALT), existing
    inventory settles out. Single-fill max loss ≈ NOTIONAL.

Paper fills (conservative, same rule as engine/paper_book.py): a resting BUY
at P fills when a trade PRINTS at ≤ P on that token (size-capped by the
print); book-cross (best_ask ≤ P) only counts if the trade feed has been
silent > TRADE_FEED_TIMEOUT.

Max logging: every quote/re-quote/cancel/fill/cutoff/settle is an event with
full book context (MM_* events in the training log).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import time
import urllib.request

from config import BAR_SECONDS, DRY_RUN, TRAINING_EVENT_LOG_PATH, log

COIN = os.getenv("COIN", "btc").lower()
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("true", "1", "yes")
_real = LIVE_TRADING and not DRY_RUN

NOTIONAL = float(os.getenv("MM_NOTIONAL_USD", "5"))          # $ per SIDE at 50c
OFFSET = float(os.getenv("MM_OFFSET_CENTS", "1")) / 100.0    # cents inside mid
REQUOTE_CENTS = float(os.getenv("MM_REQUOTE_CENTS", "2")) / 100.0
REQUOTE_MIN_AGE = float(os.getenv("MM_REQUOTE_MIN_AGE_SECS", "3"))
CUTOFF_SECS = float(os.getenv("MM_CUTOFF_SECS", "60"))       # stop quoting; cancel rest
START_DELAY = float(os.getenv("MM_START_DELAY_SECS", "3"))   # let the new book form
MID_LO = float(os.getenv("MM_MID_LO", "0.10"))               # only quote while mid in band
MID_HI = float(os.getenv("MM_MID_HI", "0.90"))
MAX_DD = float(os.getenv("MM_MAX_DD_USD", "20"))             # day kill-switch
TRADE_FEED_TIMEOUT = float(os.getenv("MM_TRADE_FEED_TIMEOUT_SECS", "45"))
TICK = 0.01
FEE_COEF = 0.07          # crypto up/down taker fee coefficient (counterparty pays)
REBATE_FRAC = 0.20       # maker rebate ≈ 20% of counterparty taker fee

from execution.events import EventLog

_event_log = EventLog(TRAINING_EVENT_LOG_PATH)


def _event(ev: str, **kw):
    _event_log.write(ev, coin=COIN, **kw)


def _http(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _slug(ws: int) -> str:
    from core.gamma import window_slug
    return window_slug(ws)


def outcome_up(ws: int):
    try:
        d = _http("https://gamma-api.polymarket.com/markets?slug=" + _slug(ws) + "&closed=true")
        if not d or not d[0].get("closed"):
            return None
        op = d[0]["outcomePrices"]
        op = json.loads(op) if isinstance(op, str) else op
        return str(op[0]) in ("1", "1.0")
    except Exception:
        return None


def est_rebate(price: float, shares: float) -> float:
    """Maker rebate estimate: REBATE_FRAC of the counterparty's taker fee."""
    return REBATE_FRAC * FEE_COEF * price * (1.0 - price) * shares


def r2(x):
    return round(x, 2) if isinstance(x, float) else x


class Quote:
    __slots__ = ("side", "token", "price", "shares", "order_id", "placed_at",
                 "filled", "fill_px", "fill_sz", "fill_basis", "fill_t")

    def __init__(self, side, token, price, shares):
        self.side = side              # "UP" | "DOWN"
        self.token = token
        self.price = price
        self.shares = shares
        self.order_id = None          # live only
        self.placed_at = time.time()
        self.filled = 0.0             # shares matched so far
        self.fill_px = price
        self.fill_sz = 0.0
        self.fill_basis = ""
        self.fill_t = 0.0


class MirrorMakerStrategy:
    """TakerRunner strategy protocol: presign_requests / on_tick / settle_loop."""

    def __init__(self) -> None:
        self.runner = None
        self.clob = None
        self.quotes: dict[str, Quote] = {}      # side -> live resting quote
        self.bar_ws: int = 0                    # bar the quotes belong to
        self.quoted_mid: float = 0.0            # up-mid at (re)quote time
        self.frozen: bool = False               # a side filled — stop re-quoting
        self.cutoff_done: bool = False
        self.halted: bool = False
        self.day_pnl: float = 0.0
        self.day_peak: float = 0.0
        self.day: str = time.strftime("%Y-%m-%d", time.gmtime())
        self.positions: dict[int, list] = {}    # ws -> [fill dicts]
        self.settled: set[int] = set()
        self.trade_cursor: int = 0
        self._last_poll: float = 0.0

    def bind(self, runner) -> None:
        self.runner = runner
        if _real:
            from engine.clob import build_clob_client, ensure_approvals
            self.clob = build_clob_client()
            ensure_approvals(self.clob)
        _event("MM_START", live=_real, notional=NOTIONAL, offset=OFFSET,
               requote_cents=REQUOTE_CENTS, cutoff=CUTOFF_SECS,
               mid_band=[MID_LO, MID_HI], max_dd=MAX_DD)

    def presign_requests(self, ctx):
        return []                                # maker bot: no FAK presigns

    # ── helpers ──────────────────────────────────────────────────────────────
    def _shares(self) -> float:
        from core.pm_ws import pm_state
        return max(pm_state.order_min_size, math.floor(NOTIONAL / 0.5))

    def _mid_up(self, ctx) -> float | None:
        if ctx.up_bid <= 0 or ctx.up_ask >= 1:
            return None
        return (ctx.up_bid + ctx.up_ask) / 2.0

    def _prices(self, ctx) -> tuple[float, float] | None:
        """(up_px, down_px): mirrored, never-cross, pair sum ≤ 1 − 2·OFFSET."""
        mid = self._mid_up(ctx)
        if mid is None or not (MID_LO <= mid <= MID_HI):
            return None
        mid_c = round(mid / TICK) * TICK
        up_px = mid_c - OFFSET
        down_px = (1.0 - mid_c) - OFFSET
        # never-cross clamp (post_only would reject; paper must not cross either)
        if ctx.up_ask > 0:
            up_px = min(up_px, ctx.up_ask - TICK)
        if ctx.down_ask > 0:
            down_px = min(down_px, ctx.down_ask - TICK)
        up_px = round(up_px, 2)
        down_px = round(down_px, 2)
        if up_px < TICK or down_px < TICK:
            return None
        return up_px, down_px

    def _book_kw(self, ctx) -> dict:
        return dict(ub=ctx.up_bid, ua=ctx.up_ask, db=ctx.down_bid, da=ctx.down_ask,
                    ubs=r2(getattr(ctx, "up_bid_size", 0.0)), uas=r2(ctx.up_ask_size),
                    das=r2(ctx.down_ask_size), t_left=round(ctx.t_left, 1))

    # ── quote lifecycle ──────────────────────────────────────────────────────
    def _place(self, ctx, reason: str) -> None:
        px = self._prices(ctx)
        if px is None:
            return
        up_px, down_px = px
        shares = self._shares()
        pair_cost = up_px + down_px
        for side, token, price in (("UP", ctx.up_token, up_px),
                                   ("DOWN", ctx.down_token, down_px)):
            q = Quote(side, token, price, shares)
            if _real:
                from engine.clob import place_limit_order
                q.order_id = place_limit_order(self.clob, token, "BUY", shares, price)
                if q.order_id is None:
                    _event("MM_POST_REJECT", side=side, price=price, **self._book_kw(ctx))
                    continue
            self.quotes[side] = q
        self.bar_ws = ctx.ws
        self.quoted_mid = self._mid_up(ctx) or 0.0
        _event("MM_QUOTE", reason=reason, up_px=up_px, down_px=down_px,
               shares=shares, pair_cost=round(pair_cost, 3),
               lock_profit=round((1 - pair_cost) * shares, 3),
               placed=sorted(self.quotes.keys()), **self._book_kw(ctx))

    def _cancel_all(self, reason: str, ctx=None) -> None:
        for side, q in list(self.quotes.items()):
            if _real and q.order_id:
                from engine.clob import cancel_order
                cancel_order(self.clob, q.order_id)
            _event("MM_CANCEL", side=side, price=q.price, reason=reason,
                   age=round(time.time() - q.placed_at, 1))
        self.quotes.clear()

    def _record_fill(self, ctx, q: Quote, sz: float, px: float, basis: str) -> None:
        q.filled += sz
        q.fill_px = px
        q.fill_basis = basis
        q.fill_t = time.time()
        self.positions.setdefault(self.bar_ws, []).append(
            dict(side=q.side, px=px, sz=sz, basis=basis,
                 t_left=round(ctx.t_left, 1)))
        self.frozen = True
        other = "DOWN" if q.side == "UP" else "UP"
        pair = other not in self.quotes or self.quotes[other].filled > 0
        _event("MM_FILL", side=q.side, px=px, sz=r2(sz), basis=basis,
               est_rebate=round(est_rebate(px, sz), 4),
               pair_complete=pair, **self._book_kw(ctx))
        if q.filled >= q.shares - 1e-9:
            self.quotes.pop(q.side, None)
        fills = self.positions.get(self.bar_ws, [])
        ups = sum(f["sz"] for f in fills if f["side"] == "UP")
        dns = sum(f["sz"] for f in fills if f["side"] == "DOWN")
        if ups > 0 and dns > 0:
            cost = sum(f["px"] * f["sz"] for f in fills)
            locked = min(ups, dns)
            _event("MM_PAIR_LOCK", up_sz=r2(ups), down_sz=r2(dns),
                   cost=round(cost, 3), locked_shares=r2(locked),
                   locked_profit=round(locked - sum(
                       f["px"] * min(f["sz"], locked) for f in fills), 3))

    # ── paper fill detection ─────────────────────────────────────────────────
    def _paper_fills(self, ctx) -> None:
        from core.pm_ws import pm_state
        new = [t for t in pm_state.recent_trades if t["seq"] > self.trade_cursor]
        if new:
            self.trade_cursor = new[-1]["seq"]
        for side, q in list(self.quotes.items()):
            if q.filled >= q.shares:
                continue
            # primary: trade prints through our price on our token
            for t in new:
                if t["token_id"] != q.token or t["price"] > q.price + 1e-9:
                    continue
                sz = min(q.shares - q.filled, t["size"])
                if sz > 0:
                    self._record_fill(ctx, q, sz, q.price, "trade_print")
                if q.filled >= q.shares:
                    break
            if q.filled >= q.shares:
                continue
            # fallback: book crossed our bid while the trade feed is silent
            ask = ctx.up_ask if side == "UP" else ctx.down_ask
            silent = (time.time() - pm_state.last_trade_ts) > TRADE_FEED_TIMEOUT
            if silent and 0 < ask <= q.price + 1e-9:
                self._record_fill(ctx, q, q.shares - q.filled, q.price, "book_cross")

    # ── live fill detection (poll; user_ws-free, $5/side tolerates 2s lag) ───
    async def _live_fills(self, ctx) -> None:
        from engine.clob import fetch_order_status
        for side, q in list(self.quotes.items()):
            if not q.order_id:
                continue
            st = await asyncio.to_thread(fetch_order_status, self.clob, q.order_id)
            if not st:
                continue
            matched = float(st.get("size_matched") or 0)
            if matched > q.filled + 1e-9:
                self._record_fill(ctx, q, matched - q.filled,
                                  float(st.get("price") or q.price), "order_status")

    # ── runner hooks ─────────────────────────────────────────────────────────
    async def on_tick(self, ctx) -> None:
        if not ctx.book_ready or not ctx.up_token:
            return
        # new bar → reset per-bar state (old quotes died with the old market)
        if ctx.ws != self.bar_ws and self.quotes:
            self._cancel_all("bar_roll")
        if ctx.ws != self.bar_ws:
            self.frozen = False
            self.cutoff_done = False

        # fill detection first (applies to resting quotes)
        if self.quotes and ctx.ws == self.bar_ws:
            if _real:
                # REST poll — throttle; the tick bus fires 100s of wakes/sec
                if ctx.now - self._last_poll >= 1.5:
                    self._last_poll = ctx.now
                    await self._live_fills(ctx)
            else:
                self._paper_fills(ctx)

        # cutoff: cancel resting, no new quotes this bar
        if ctx.t_left < CUTOFF_SECS:
            if self.quotes and not self.cutoff_done:
                self._cancel_all("cutoff", ctx)
            if not self.cutoff_done:
                self.cutoff_done = True
                fills = self.positions.get(ctx.ws, [])
                _event("MM_CUTOFF", n_fills=len(fills),
                       sides=sorted({f["side"] for f in fills}), **self._book_kw(ctx))
            return

        if self.halted or self.frozen:
            return

        bar_age = (BAR_SECONDS - ctx.t_left)
        if bar_age < START_DELAY:
            return

        if not self.quotes and ctx.ws not in self.positions:
            self._place(ctx, "open")
            return

        # re-quote on drift (only while nothing filled)
        if self.quotes and self.bar_ws == ctx.ws:
            mid = self._mid_up(ctx)
            age = time.time() - min(q.placed_at for q in self.quotes.values())
            if (mid is not None and abs(mid - self.quoted_mid) >= REQUOTE_CENTS
                    and age >= REQUOTE_MIN_AGE):
                self._cancel_all("drift", ctx)
                self._place(ctx, "requote")

    async def settle_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            try:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                if today != self.day:
                    _event("MM_DAY_SUMMARY", day=self.day, pnl=round(self.day_pnl, 2))
                    self.day = today
                    self.day_pnl = 0.0
                    self.day_peak = 0.0
                    self.halted = False
                now = time.time()
                for ws in [w for w in self.positions if w + BAR_SECONDS < now - 10]:
                    oc = await asyncio.to_thread(outcome_up, ws)
                    if oc is None:
                        if now - (ws + BAR_SECONDS) > 600:
                            _event("MM_SETTLE_TIMEOUT", bar=ws)
                            self.positions.pop(ws, None)
                        continue
                    fills = self.positions.pop(ws)
                    pnl = 0.0
                    rebate = 0.0
                    for f in fills:
                        payoff = 1.0 if ((f["side"] == "UP") == oc) else 0.0
                        pnl += (payoff - f["px"]) * f["sz"]
                        rebate += est_rebate(f["px"], f["sz"])
                    ups = sum(f["sz"] for f in fills if f["side"] == "UP")
                    dns = sum(f["sz"] for f in fills if f["side"] == "DOWN")
                    status = ("both" if ups > 0 and dns > 0 else
                              ("up_only" if ups > 0 else "down_only"))
                    self.day_pnl += pnl
                    self.day_peak = max(self.day_peak, self.day_pnl)
                    dd = self.day_peak - self.day_pnl
                    _event("MM_BAR_SETTLE", bar=ws, outcome="UP" if oc else "DOWN",
                           pair_status=status, n_fills=len(fills),
                           pnl=round(pnl, 3), est_rebate=round(rebate, 4),
                           day_pnl=round(self.day_pnl, 2), day_dd=round(dd, 2))
                    if dd >= MAX_DD and not self.halted:
                        self.halted = True
                        _event("MM_HALT", day_pnl=round(self.day_pnl, 2),
                               day_dd=round(dd, 2), max_dd=MAX_DD)
                    self.settled.add(ws)
            except Exception as exc:
                log.exception("settle loop: %s", exc)


def main():
    from execution.runner import TakerRunner
    log.info("mirror_maker %s: coin=%s $%s/side offset=%sc requote=%sc cutoff=%ss maxDD=$%s",
             "LIVE" if _real else "PAPER", COIN, NOTIONAL, OFFSET * 100,
             REQUOTE_CENTS * 100, CUTOFF_SECS, MAX_DD)
    runner = TakerRunner(MirrorMakerStrategy(), live=_real, event_logger=_event)
    asyncio.run(runner.run())


if __name__ == "__main__":
    main()
