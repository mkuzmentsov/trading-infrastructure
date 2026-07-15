"""Maker-rebate quoting strategy (paper-only in v1).

Flips the bot's role from taker to maker: every 5m bar, rest a BUY on BOTH
tokens (UP and DOWN) at mid − halfSpread, clamped to the high-rebate
[quoteFloor, quoteCeil] band, with up_quote + down_quote < 1 − minPairEdge so
a both-sides fill locks 1 − (b_u + b_d) profit at settle.

Adverse-selection mitigations (the core of the strategy — see PLAN.md):
  * warmup: no quotes for the first QUOTE_WARMUP_SECS of the bar;
  * hard cutoff: at seconds_left <= QUOTE_CUTOFF_SECS cancel everything and
    stop quoting — never rest quotes in the late-bar sniping window;
  * reprice on movement: cancel/replace when the desired quote drifts more
    than REPRICE_TICKS or the spot feed moves more than REPRICE_Z sigmas
    since the quote was placed;
  * inventory cap: stop quoting a side once its filled inventory this bar
    reaches MAX_INVENTORY_SHARES.

Filled inventory holds to expiry (v1); settlement lives in the engine.

Engine selection (main.py wires the matching book):
  * PAPER_MODE=true  → paper_book (simulated fills, no CLOB calls — the fleet
    data-collection path, unchanged);
  * PAPER_MODE=false + LIVE_TRADING=true + DRY_RUN=false + creds → live_book
    (real signed GTC orders, never-cross guard, daily-loss kill switch);
  * anything ambiguous → hard error at construction.
"""
from __future__ import annotations

import math

from config import (
    DRY_RUN,
    BAR_SNAPSHOT_SECS,
    BRACKET_SIDES,
    BRACKET_SIDE_RULE,
    ENTRY_PRICE_CAP,
    ENTRY_STYLE,
    LIVE_MAX_ORDER_USD,
    LIVE_QUOTE_WARMUP_SECS,
    LIVE_TRADING,
    MAX_FILLS_PER_BAR,
    MAX_INVENTORY_SHARES,
    MIN_PAIR_EDGE,
    PAPER_MODE,
    POLYMARKET_PK,
    QUOTE_CEIL,
    QUOTE_CUTOFF_SECS,
    QUOTE_FLOOR,
    QUOTE_HALF_SPREAD,
    QUOTE_MODE,
    QUOTE_MODEL_MARGIN,
    LOCK_MAX_UNMATCHED,
    LOCK_MOM_BRAKE_Z,
    LOCK_ASYM_MOM_Z,
    LOCK_ASYM_EXTRA,
    LOCK_COMPLETION_MARGIN,
    LOCK_PAIR_TARGET,
    QUOTE_NOTIONAL_USD,
    QUOTE_SIDE,
    QUOTE_SIZE,
    QUOTE_WARMUP_SECS,
    REPRICE_TICKS,
    REPRICE_Z,
    STOP_LOSS_PRICE,
    TAKE_PROFIT_PRICE,
    log,
)
from .math_signal import Signal, _fair_p_up
from .side_rules import pick_side
from core.positions import Position

from .base import PositionDecision, StrategyContext

_TICK = 0.01


def _round_down_tick(price: float) -> float:
    return math.floor(price / _TICK + 1e-9) * _TICK


class MakerRebateStrategy:
    name = "maker_rebate"

    def __init__(self) -> None:
        # Engine gates — paper → paper_book, live → live_book, anything
        # ambiguous → hard error (all gates must pass to run live).
        if PAPER_MODE and LIVE_TRADING:
            raise RuntimeError(
                "maker_rebate: AMBIGUOUS config — PAPER_MODE=true AND LIVE_TRADING=true. "
                "Pick exactly one (paper: PAPER_MODE=true; live: PAPER_MODE=false LIVE_TRADING=true DRY_RUN=false)."
            )
        if PAPER_MODE:
            self._live = False
        else:
            if not LIVE_TRADING:
                raise RuntimeError(
                    "maker_rebate: PAPER_MODE=false but LIVE_TRADING is not 'true' — refusing to start. "
                    "Live trading must be enabled EXPLICITLY with LIVE_TRADING=true."
                )
            if DRY_RUN:
                raise RuntimeError(
                    "maker_rebate: AMBIGUOUS config — LIVE_TRADING=true with DRY_RUN=true. "
                    "Set DRY_RUN=false for live trading."
                )
            if not POLYMARKET_PK:
                raise RuntimeError(
                    "maker_rebate: LIVE_TRADING=true but POLYMARKET_PK is missing — refusing to start."
                )
            self._live = True
        # Warmup: live defaults to 0 (entry on the book at bar roll — the
        # latency edge); paper keeps QUOTE_WARMUP_SECS. Both env-overridable.
        self._warmup = LIVE_QUOTE_WARMUP_SECS if self._live else QUOTE_WARMUP_SECS
        # USD entry budget; the live hard cap wins if the knob exceeds it.
        self._notional = QUOTE_NOTIONAL_USD
        if self._live and LIVE_MAX_ORDER_USD > 0 and self._notional > LIVE_MAX_ORDER_USD:
            log.warning(
                "QUOTE_NOTIONAL_USD %.2f exceeds LIVE_MAX_ORDER_USD %.2f — clamped to the live cap",
                self._notional, LIVE_MAX_ORDER_USD,
            )
            self._notional = LIVE_MAX_ORDER_USD
        # Bracket-mode per-bar state: the side is LOCKED when first chosen and
        # never flips mid-bar.
        # model-mode v2 per-tick scratch: book handle (for pair completion) and
        # per-side completion sizes chosen by desired_quotes.
        self._quote_book = None
        self._want_size: dict[str, float] = {}
        self._bracket_cid: str = ""
        self._bracket_side: str | None = None
        self._bracket_p_up: float = 0.5
        self._bracket_p_up_source: str = ""
        # Startup gate: never start trading mid-bar. The first bar observed
        # after (re)deploy is skipped when it's already >10s old — a mid-bar
        # entry sees an already-moved tape (inflated p_up) and partial-bar
        # exposure. Trading begins at the next bar boundary.
        self._startup_checked = False
        self._startup_skip_cid: str = ""
        self._last_snapshot: float = 0.0
        self._last_alt_side: str = "DOWN"  # alternate rule starts with UP

    # ── Strategy protocol (taker path is never used; keep it inert) ─────────
    def startup_details(self) -> list[str]:
        engine = "LIVE" if self._live else "PAPER"
        sizing = (
            f"notional=${self._notional:.2f}" if self._notional > 0 else f"size={QUOTE_SIZE}"
        )
        details = [
            f"maker_rebate {engine}  mode={QUOTE_MODE}  side={QUOTE_SIDE if QUOTE_MODE == 'one_sided' else '-'}  "
            f"halfSpread={QUOTE_HALF_SPREAD:.3f}  band=[{QUOTE_FLOOR:.2f},{QUOTE_CEIL:.2f}]",
            f"  {sizing}  cutoff={QUOTE_CUTOFF_SECS}s  warmup={self._warmup}s  "
            f"minPairEdge={MIN_PAIR_EDGE:.3f}  repriceTicks={REPRICE_TICKS:.3f}  repriceZ={REPRICE_Z:.2f}  "
            f"maxInv={MAX_INVENTORY_SHARES}",
        ]
        if QUOTE_MODE == "bracket":
            details.append(
                f"  bracket: entryCap={ENTRY_PRICE_CAP:.2f}  tp={TAKE_PROFIT_PRICE:.2f}  "
                f"stop={STOP_LOSS_PRICE:.2f}  maxFillsPerBar={MAX_FILLS_PER_BAR}"
            )
        return details

    def entry_order_mode(self) -> str:
        return "paper"

    def entry_hold_to_expiry(self) -> bool:
        return True

    def evaluate_entry(self, ctx: StrategyContext) -> Signal:
        return Signal(
            action="NO_TRADE",
            price=None,
            size=0,
            p_up=0.5,
            edge=0.0,
            reason="maker_rebate quotes via the paper maker tick, not the taker entry path",
        )

    def evaluate_position(
        self, ctx: StrategyContext, pos: Position, current_bid: float, now: float
    ) -> PositionDecision:
        return PositionDecision()

    # ── Quote maintenance (called from main's maker tick) ───────────────────
    def desired_quotes(self, ctx: StrategyContext) -> dict[str, float]:
        """Compute the desired bid per side. Empty dict = no quotes."""
        if not (0 < ctx.up_bid <= ctx.up_ask < 1) or not (0 < ctx.down_bid <= ctx.down_ask < 1):
            return {}
        up_mid = (ctx.up_bid + ctx.up_ask) / 2.0
        down_mid = (ctx.down_bid + ctx.down_ask) / 2.0

        if QUOTE_MODE == "model":
            # model-priced two-sided quoting (leaderboard "lock accumulator"):
            # bid each side at its fair probability minus a margin, so fills
            # only come from takers crossing through fair value. v2 (measured
            # on the first 55 bars: locked pairs +EV, one-sided bleeds):
            #   * momentum brake — pull everything during violent 30s moves
            #     (that's when the trailing quote is a falling-knife catcher);
            #   * asymmetric margin — the against-momentum side quotes deeper;
            #   * pair completion — once one side holds unmatched inventory,
            #     chase the other side (small margin) while the completed
            #     pair still costs <= LOCK_PAIR_TARGET, converting one-sided
            #     risk into a locked spread.
            sig30 = ctx.sigma_5m * math.sqrt(30.0 / 300.0)
            mom_z = (ctx.ret_30s / sig30) if sig30 > 0 else 0.0
            if abs(mom_z) > LOCK_MOM_BRAKE_Z:
                self._want_size = {}
                return {}
            p_up, _src = self._bracket_p_up_estimate(ctx)
            m_up = QUOTE_MODEL_MARGIN + (LOCK_ASYM_EXTRA if mom_z < -LOCK_ASYM_MOM_Z else 0.0)
            m_dn = QUOTE_MODEL_MARGIN + (LOCK_ASYM_EXTRA if mom_z > LOCK_ASYM_MOM_Z else 0.0)
            up_q = min(max(p_up - m_up, QUOTE_FLOOR), QUOTE_CEIL)
            down_q = min(max((1.0 - p_up) - m_dn, QUOTE_FLOOR), QUOTE_CEIL)
            self._want_size = {}
            self._skip_sides = set()
            book = self._quote_book
            if book is not None:
                inv_up = book.bar_inventory("UP")
                inv_dn = book.bar_inventory("DOWN")
                unmatched = inv_up - inv_dn
                avg_cost = getattr(book, "bar_avg_cost", lambda d: 0.0)
                if unmatched > 1.0:        # UP-heavy → chase DOWN to complete
                    comp_q = min((1.0 - p_up) - LOCK_COMPLETION_MARGIN,
                                 LOCK_PAIR_TARGET - avg_cost("UP"), QUOTE_CEIL)
                    if comp_q >= QUOTE_FLOOR:   # below floor → pair can't lock, keep normal quote
                        down_q = comp_q
                        self._want_size["DOWN"] = min(float(QUOTE_SIZE), unmatched)
                    # v3: heavy side stops adding one-sided exposure at the cap
                    if unmatched >= LOCK_MAX_UNMATCHED:
                        self._skip_sides.add("UP")
                elif unmatched < -1.0:     # DOWN-heavy → chase UP to complete
                    comp_q = min(p_up - LOCK_COMPLETION_MARGIN,
                                 LOCK_PAIR_TARGET - avg_cost("DOWN"), QUOTE_CEIL)
                    if comp_q >= QUOTE_FLOOR:
                        up_q = comp_q
                        self._want_size["UP"] = min(float(QUOTE_SIZE), -unmatched)
                    if -unmatched >= LOCK_MAX_UNMATCHED:
                        self._skip_sides.add("DOWN")
        else:
            up_q = min(max(up_mid - QUOTE_HALF_SPREAD, QUOTE_FLOOR), QUOTE_CEIL)
            down_q = min(max(down_mid - QUOTE_HALF_SPREAD, QUOTE_FLOOR), QUOTE_CEIL)

        # Pair-lock constraint: up_q + down_q < 1 − minPairEdge. Shave both
        # sides equally; if one hits the floor, take the rest from the other.
        budget = 1.0 - MIN_PAIR_EDGE
        excess = (up_q + down_q) - budget
        if excess > 0:
            up_q -= excess / 2.0
            down_q -= excess / 2.0
            if up_q < QUOTE_FLOOR:
                down_q -= QUOTE_FLOOR - up_q
                up_q = QUOTE_FLOOR
            elif down_q < QUOTE_FLOOR:
                up_q -= QUOTE_FLOOR - down_q
                down_q = QUOTE_FLOOR
            if up_q < QUOTE_FLOOR or down_q < QUOTE_FLOOR:
                return {}  # constraint infeasible inside the band — stand down

        up_q = _round_down_tick(up_q)
        down_q = _round_down_tick(down_q)

        # Never cross the book — a crossing "quote" would be a taker order.
        if up_q >= ctx.up_ask:
            up_q = _round_down_tick(ctx.up_ask - _TICK)
        if down_q >= ctx.down_ask:
            down_q = _round_down_tick(ctx.down_ask - _TICK)

        quotes: dict[str, float] = {}
        if QUOTE_FLOOR <= up_q <= QUOTE_CEIL:
            quotes["UP"] = up_q
        if QUOTE_FLOOR <= down_q <= QUOTE_CEIL:
            quotes["DOWN"] = down_q
        for side in getattr(self, "_skip_sides", ()):   # v3 unmatched cap
            quotes.pop(side, None)

        # one_sided mode: keep exactly one quote per bar (rebate-collection
        # test — EV/share = fill_win_rate − price; see PLAN.md §2b).
        if QUOTE_MODE == "one_sided" and quotes:
            side = self._pick_side(ctx, up_mid, down_mid)
            quotes = {side: quotes[side]} if side in quotes else {}
        return quotes

    def _pick_side(self, ctx: StrategyContext, up_mid: float, down_mid: float) -> str:
        if QUOTE_SIDE == "up":
            return "UP"
        if QUOTE_SIDE == "down":
            return "DOWN"
        if QUOTE_SIDE == "alternate":
            # Flip by bar window parity — deterministic and unbiased across bars.
            from core.pm_ws import pm_state
            bar_idx = int(pm_state.market_start_ts // 300) if pm_state.market_start_ts else 0
            return "UP" if bar_idx % 2 == 0 else "DOWN"
        # "cheaper" (default): the side with mid ≤ 0.5 — closest to the p(1−p)
        # rebate-weight peak and the least $ at risk per share.
        return "UP" if up_mid <= down_mid else "DOWN"

    def _spot_z_move(self, ctx: StrategyContext, spot_at_place: float) -> float:
        if spot_at_place <= 0 or ctx.current_price <= 0 or ctx.sigma_5m <= 0:
            return 0.0
        return abs(math.log(ctx.current_price / spot_at_place)) / ctx.sigma_5m

    def _entry_size(self, price: float) -> tuple[float, bool]:
        """USD-denominated bracket sizing: QUOTE_NOTIONAL_USD / price, floored
        to whole shares (lot step), then clamped UP to the market's
        orderMinSize (gamma payload, fallback 5). Returns (shares,
        size_clamped_to_min). Falls back to legacy QUOTE_SIZE shares when the
        notional knob is unset/0."""
        if self._notional <= 0 or price <= 0:
            return float(QUOTE_SIZE), False
        from core.pm_ws import pm_state
        shares = float(math.floor(self._notional / price))
        min_size = float(pm_state.order_min_size or 5.0)
        if shares < min_size:
            log.info(
                "Entry size clamped UP to orderMinSize  %.0f → %.0f shares @ %.3f (notional=$%.2f)",
                shares, min_size, price, self._notional,
            )
            return min_size, True
        return shares, False

    # ── Bracket mode (default): predict side, one entry fill, TP/SL bracket ──
    def _bracket_p_up_estimate(self, ctx: StrategyContext) -> tuple[float, str]:
        """Cheapest p_up for the current bar: the blended ML probability when
        the caller provides one, else math_signal's closed-form fair p_up,
        else the momentum sign of ret_60s."""
        if ctx.ml_p_up is not None and math.isfinite(ctx.ml_p_up):
            return float(ctx.ml_p_up), "ml_p_up"
        best_price = ctx.binance_price if ctx.binance_price > 0 else ctx.current_price
        if ctx.bar_open > 0 and best_price > 0 and ctx.sigma_5m > 0:
            return (
                _fair_p_up(ctx.bar_open, best_price, ctx.sigma_5m, ctx.seconds_left),
                "math_signal",
            )
        if ctx.ret_60s > 0:
            return 0.6, "ret_60s_momentum"
        if ctx.ret_60s < 0:
            return 0.4, "ret_60s_momentum"
        return 0.5, "ret_60s_momentum_flat"

    def _maintain_bracket(self, ctx: StrategyContext, book, now: float) -> None:
        from core.pm_ws import pm_state

        # New bar → forget the locked side.
        if pm_state.condition_id != self._bracket_cid:
            self._bracket_cid = pm_state.condition_id
            self._bracket_side = None

        # Hard cutoff — pull the ENTRY quote only; the bracket exits (resting
        # TP + taker stop) stay armed until settle, they only reduce risk.
        if ctx.seconds_left <= QUOTE_CUTOFF_SECS:
            book.cancel_entries("quote_cutoff", now)
            return

        # Warmup after bar open (live default 0 — entry lands at bar roll).
        bar_len = max(1, ctx.seconds_left)
        if pm_state.market_start_ts > 0 and pm_state.market_end_ts > 0:
            bar_len = pm_state.market_end_ts - pm_state.market_start_ts
        elapsed = bar_len - ctx.seconds_left
        if elapsed < self._warmup:
            return

        # Startup gate: skip the bar already in progress at (re)deploy.
        if not self._startup_checked:
            self._startup_checked = True
            if elapsed > 10:
                self._startup_skip_cid = pm_state.condition_id
                log.info(
                    "STARTUP mid-bar (elapsed=%.0fs) — skipping this bar, trading starts next bar",
                    elapsed,
                )
        if self._startup_skip_cid and pm_state.condition_id == self._startup_skip_cid:
            return

        # Which sides to quote this bar. "both": rest the fixed entry on UP
        # AND DOWN — a both-fill pair costs 2×ENTRY_PRICE_CAP < 1 and settles
        # at exactly $1, i.e. it can never lose; a single fill is the same
        # one-sided bet as "one" mode minus the side prediction. "one": lock
        # the predicted side once per bar (original behavior).
        if BRACKET_SIDES == "both":
            sides = ("UP", "DOWN")
        else:
            if self._bracket_side is None:
                p_up, source = self._bracket_p_up_estimate(ctx)
                self._bracket_side, source, self._last_alt_side = pick_side(
                    BRACKET_SIDE_RULE, p_up, source, self._last_alt_side
                )
                self._bracket_p_up = p_up
                self._bracket_p_up_source = source
                if hasattr(book, "set_bar_meta"):
                    book.set_bar_meta(
                        p_up=round(p_up, 4), p_up_source=source,
                        side_rule=BRACKET_SIDE_RULE,
                    )
                log.info(
                    "BRACKET side locked  side=%s  p_up=%.3f  source=%s  rule=%s  secs_left=%d",
                    self._bracket_side, p_up, source, BRACKET_SIDE_RULE, ctx.seconds_left,
                )
            sides = (self._bracket_side,)

        for side in sides:
            self._maintain_bracket_side(ctx, book, now, side)

    def _maintain_bracket_side(
        self, ctx: StrategyContext, book, now: float, side: str
    ) -> None:
        # Max ONE fill per bar per side (MAX_FILLS_PER_BAR): once this side's
        # entry filled, stand down — no refill conveyor. The engine already
        # cancelled the remainder at fill time; this keeps us from re-placing.
        if book.bar_entry_fills(side) >= MAX_FILLS_PER_BAR:
            book.cancel_entries("max_fills_per_bar", now, direction=side)
            return

        bid, ask = (ctx.up_bid, ctx.up_ask) if side == "UP" else (ctx.down_bid, ctx.down_ask)
        if not (0 < bid <= ask < 1):
            if self._live:
                # LIVE latency path: the book hasn't formed yet at bar roll —
                # a non-marketable bid near 50c is safe by construction, so
                # place it NOW instead of waiting. (chase style repriced it on
                # the first snapshot; fixed style just lets it rest.)
                want = _round_down_tick(min(0.49, ENTRY_PRICE_CAP))
                if want >= _TICK and book.resting_entry(side) is None:
                    size, clamped = self._entry_size(want)
                    book.place_quote(
                        side, want, size, now,
                        purpose="entry", size_clamped_to_min=clamped,
                    )
                return
            book.cancel_entries("book_not_live", now, direction=side)
            return
        mid = (bid + ask) / 2.0

        if ENTRY_STYLE == "fixed":
            # Rest AT the cap (≤50c = max p(1−p) rebate weight); clamp to
            # ask − tick only if the cap would cross (always maker, never
            # taker — a 47c rest is fine). Below QUOTE_FLOOR the side is
            # already decided-cheap: those fills measured q − p < 0, skip.
            want = _round_down_tick(ENTRY_PRICE_CAP)
            if want >= ask:
                want = _round_down_tick(ask - _TICK)
            if want < max(QUOTE_FLOOR, _TICK):
                book.cancel_entries("below_floor", now, direction=side)
                return
            # No repricing: the order rests untouched until fill or cutoff.
            resting = book.resting_entry(side)
        else:
            # chase: bid mid − halfSpread, capped at ENTRY_PRICE_CAP.
            # Round down; never cross; cancel/replace on drift.
            want = _round_down_tick(min(mid - QUOTE_HALF_SPREAD, ENTRY_PRICE_CAP))
            if want >= ask:
                want = _round_down_tick(ask - _TICK)
            if want < _TICK:
                book.cancel_entries("no_quote_band", now, direction=side)
                return

            resting = book.resting_entry(side)
            if resting is not None:
                stale_price = abs(want - resting.price) > REPRICE_TICKS + 1e-9
                stale_z = self._spot_z_move(ctx, resting.spot_at_place) > REPRICE_Z
                if stale_price or stale_z:
                    book.cancel_quote(
                        resting.order_id,
                        "reprice_mid_moved" if stale_price else "reprice_spot_z",
                        now,
                    )
                    resting = None

        if resting is None:
            size, clamped = self._entry_size(want)
            book.place_quote(
                side, want, size, now, purpose="entry", size_clamped_to_min=clamped
            )

    def _maybe_snapshot(self, ctx: StrategyContext, book, now: float) -> None:
        """Every BAR_SNAPSHOT_SECS: log the book + spot so offline analysis
        can reconstruct in-bar paths (recovery curves, imbalance toxicity)."""
        if BAR_SNAPSHOT_SECS <= 0 or now - self._last_snapshot < BAR_SNAPSHOT_SECS:
            return
        self._last_snapshot = now
        from core.pm_ws import pm_state
        book._event(
            "bar_snapshot",
            seconds_left=ctx.seconds_left,
            up_bid=ctx.up_bid, up_ask=ctx.up_ask,
            down_bid=ctx.down_bid, down_ask=ctx.down_ask,
            up_bid_size=getattr(pm_state, "up_bid_size", 0.0),
            up_ask_size=getattr(pm_state, "up_ask_size", 0.0),
            down_bid_size=getattr(pm_state, "down_bid_size", 0.0),
            down_ask_size=getattr(pm_state, "down_ask_size", 0.0),
            spot=ctx.current_price, bar_open=ctx.bar_open,
        )

    def maintain_quotes(self, ctx: StrategyContext, book, now: float) -> None:
        """Bring resting paper quotes in line with the desired state."""
        if not book.bar_active():
            book.cancel_all("no_active_bar", now)
            return

        self._maybe_snapshot(ctx, book, now)

        if QUOTE_MODE == "bracket":
            self._maintain_bracket(ctx, book, now)
            return

        # Hard cutoff — never rest quotes in the sniping window.
        if ctx.seconds_left <= QUOTE_CUTOFF_SECS:
            book.cancel_all("quote_cutoff", now)
            return

        # Warmup after bar open.
        bar_len = max(1, ctx.seconds_left)  # fallback if window unknown
        from core.pm_ws import pm_state
        if pm_state.market_start_ts > 0 and pm_state.market_end_ts > 0:
            bar_len = pm_state.market_end_ts - pm_state.market_start_ts
        elapsed = bar_len - ctx.seconds_left
        if elapsed < self._warmup:
            return

        self._quote_book = book
        desired = self.desired_quotes(ctx)

        for direction in ("UP", "DOWN"):
            resting = book.resting_quote(direction)
            want = desired.get(direction)

            # Inventory cap: stop quoting a filled-up side.
            if book.bar_inventory(direction) >= MAX_INVENTORY_SHARES:
                if resting is not None:
                    book.cancel_quote(resting.order_id, "inventory_cap", now)
                continue

            if want is None:
                if resting is not None:
                    book.cancel_quote(resting.order_id, "no_quote_band", now)
                continue

            if resting is not None:
                stale_price = abs(want - resting.price) > REPRICE_TICKS + 1e-9
                stale_z = self._spot_z_move(ctx, resting.spot_at_place) > REPRICE_Z
                if stale_price or stale_z:
                    book.cancel_quote(
                        resting.order_id,
                        "reprice_mid_moved" if stale_price else "reprice_spot_z",
                        now,
                    )
                    resting = None

            if resting is None:
                size = self._want_size.get(direction, float(QUOTE_SIZE))
                book.place_quote(direction, want, size, now)

        if desired:
            log.debug(
                "Maker quotes maintained  desired=%s  secs_left=%d  inv_up=%.1f inv_down=%.1f",
                desired, ctx.seconds_left, book.bar_inventory("UP"), book.bar_inventory("DOWN"),
            )
