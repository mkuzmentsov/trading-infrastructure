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

Filled inventory holds to expiry (v1); settlement lives in paper_book.

This strategy NEVER touches the CLOB — it refuses to construct unless
PAPER_MODE is set, and all order flow goes through the paper engine.
"""
from __future__ import annotations

import math

from config import (
    ENTRY_PRICE_CAP,
    MAX_FILLS_PER_BAR,
    MAX_INVENTORY_SHARES,
    MIN_PAIR_EDGE,
    PAPER_MODE,
    QUOTE_CEIL,
    QUOTE_CUTOFF_SECS,
    QUOTE_FLOOR,
    QUOTE_HALF_SPREAD,
    QUOTE_MODE,
    QUOTE_SIDE,
    QUOTE_SIZE,
    QUOTE_WARMUP_SECS,
    REPRICE_TICKS,
    REPRICE_Z,
    STOP_LOSS_PRICE,
    TAKE_PROFIT_PRICE,
    log,
)
from math_signal import Signal, _fair_p_up
from positions import Position

from .base import PositionDecision, StrategyContext

_TICK = 0.01


def _round_down_tick(price: float) -> float:
    return math.floor(price / _TICK + 1e-9) * _TICK


class MakerRebateStrategy:
    name = "maker_rebate"

    def __init__(self) -> None:
        if not PAPER_MODE:
            raise RuntimeError(
                "maker_rebate v1 is paper-only — set PAPER_MODE=true (live quoting is not implemented)"
            )
        # Bracket-mode per-bar state: the side is LOCKED when first chosen and
        # never flips mid-bar.
        self._bracket_cid: str = ""
        self._bracket_side: str | None = None
        self._bracket_p_up: float = 0.5
        self._bracket_p_up_source: str = ""

    # ── Strategy protocol (taker path is never used; keep it inert) ─────────
    def startup_details(self) -> list[str]:
        details = [
            f"maker_rebate PAPER  mode={QUOTE_MODE}  side={QUOTE_SIDE if QUOTE_MODE == 'one_sided' else '-'}  "
            f"halfSpread={QUOTE_HALF_SPREAD:.3f}  band=[{QUOTE_FLOOR:.2f},{QUOTE_CEIL:.2f}]",
            f"  size={QUOTE_SIZE}  cutoff={QUOTE_CUTOFF_SECS}s  warmup={QUOTE_WARMUP_SECS}s  "
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
            from pm_ws import pm_state
            bar_idx = int(pm_state.market_start_ts // 300) if pm_state.market_start_ts else 0
            return "UP" if bar_idx % 2 == 0 else "DOWN"
        # "cheaper" (default): the side with mid ≤ 0.5 — closest to the p(1−p)
        # rebate-weight peak and the least $ at risk per share.
        return "UP" if up_mid <= down_mid else "DOWN"

    def _spot_z_move(self, ctx: StrategyContext, spot_at_place: float) -> float:
        if spot_at_place <= 0 or ctx.current_price <= 0 or ctx.sigma_5m <= 0:
            return 0.0
        return abs(math.log(ctx.current_price / spot_at_place)) / ctx.sigma_5m

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
        from pm_ws import pm_state

        # New bar → forget the locked side.
        if pm_state.condition_id != self._bracket_cid:
            self._bracket_cid = pm_state.condition_id
            self._bracket_side = None

        # Hard cutoff — pull the ENTRY quote only; the bracket exits (resting
        # TP + taker stop) stay armed until settle, they only reduce risk.
        if ctx.seconds_left <= QUOTE_CUTOFF_SECS:
            book.cancel_entries("quote_cutoff", now)
            return

        # Warmup after bar open.
        bar_len = max(1, ctx.seconds_left)
        if pm_state.market_start_ts > 0 and pm_state.market_end_ts > 0:
            bar_len = pm_state.market_end_ts - pm_state.market_start_ts
        elapsed = bar_len - ctx.seconds_left
        if elapsed < QUOTE_WARMUP_SECS:
            return

        # Max ONE fill per bar (MAX_FILLS_PER_BAR): once the entry filled,
        # stand down — no refill conveyor. paper_book already cancelled the
        # remainder at fill time; this keeps us from re-placing.
        if book.bar_entry_fills() >= MAX_FILLS_PER_BAR:
            book.cancel_entries("max_fills_per_bar", now)
            return

        # Lock the side the first time we're ready to quote this bar.
        if self._bracket_side is None:
            p_up, source = self._bracket_p_up_estimate(ctx)
            self._bracket_side = "UP" if p_up >= 0.5 else "DOWN"
            self._bracket_p_up = p_up
            self._bracket_p_up_source = source
            log.info(
                "BRACKET side locked  side=%s  p_up=%.3f  source=%s  secs_left=%d",
                self._bracket_side, p_up, source, ctx.seconds_left,
            )
        side = self._bracket_side

        bid, ask = (ctx.up_bid, ctx.up_ask) if side == "UP" else (ctx.down_bid, ctx.down_ask)
        if not (0 < bid <= ask < 1):
            book.cancel_entries("book_not_live", now)
            return
        mid = (bid + ask) / 2.0

        # Entry bid: mid − halfSpread, capped so fills stay <= ENTRY_PRICE_CAP
        # (max p(1−p) rebate weight, never overpay). Round down; never cross.
        want = _round_down_tick(min(mid - QUOTE_HALF_SPREAD, ENTRY_PRICE_CAP))
        if want >= ask:
            want = _round_down_tick(ask - _TICK)
        if want < _TICK:
            book.cancel_entries("no_quote_band", now)
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
            book.place_quote(side, want, float(QUOTE_SIZE), now, purpose="entry")

    def maintain_quotes(self, ctx: StrategyContext, book, now: float) -> None:
        """Bring resting paper quotes in line with the desired state."""
        if not book.bar_active():
            book.cancel_all("no_active_bar", now)
            return

        if QUOTE_MODE == "bracket":
            self._maintain_bracket(ctx, book, now)
            return

        # Hard cutoff — never rest quotes in the sniping window.
        if ctx.seconds_left <= QUOTE_CUTOFF_SECS:
            book.cancel_all("quote_cutoff", now)
            return

        # Warmup after bar open.
        bar_len = max(1, ctx.seconds_left)  # fallback if window unknown
        from pm_ws import pm_state
        if pm_state.market_start_ts > 0 and pm_state.market_end_ts > 0:
            bar_len = pm_state.market_end_ts - pm_state.market_start_ts
        elapsed = bar_len - ctx.seconds_left
        if elapsed < QUOTE_WARMUP_SECS:
            return

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
                book.place_quote(direction, want, float(QUOTE_SIZE), now)

        if desired:
            log.debug(
                "Maker quotes maintained  desired=%s  secs_left=%d  inv_up=%.1f inv_down=%.1f",
                desired, ctx.seconds_left, book.bar_inventory("UP"), book.bar_inventory("DOWN"),
            )
