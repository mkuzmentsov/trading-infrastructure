"""Pure-math, time-aware smart entry/exit strategy.

Drops the ML models (they've been marginal) and leans fully on the Binance
latency edge, but is smarter than `latency_arb_hold` about when to enter and
when to bail out early:

Entry
  * z-score of BTC log-distance from bar_open vs remaining-bar sigma.
  * Time-scaled z threshold: early bars need a bigger move (more time to
    revert), late bars accept smaller z.
  * Hard price floor 0.30 / ceiling 0.70 on the side we buy — cheap tails
    (<0.30) are the WR drag; expensive (>0.70) have no upside left.
  * Late-bar override: with <45s left AND z > 2.5, floor drops to 0.15 and
    ceiling rises to 0.88.
  * Book-divergence filter kept (book hasn't repriced the BTC move yet).
  * Size scaled by z: clamp(z/2, 0.5x, 2.0x) of the default stake.

Exits (strategy owns all of them — no outer TP/SL applied)
  * thesis_break: BTC moved AGAINST us by more than THESIS_MIN_BTC_DISTANCE
    while >60s remain → cut the loss, don't wait for expiry.
  * profit_lock_trail: once unrealized >= 0.10, arm trailing; exit if bid
    falls TRAILING_STOP_GAP from peak.
  * late_bar_skim: with <90s left and bid >= 0.88 → sell now, avoid oracle
    flip risk in the last minute.
  * late_bar_salvage: with <45s left and thesis no longer alive → exit.
  * Otherwise hold to expiry — signal edge is at entry, not exit timing.
"""
from __future__ import annotations

import math

from config import (
    BAR_DURATION_SECS,
    ENTRY_ORDER_MODE,
    MAX_ENTRY_SPREAD,
    MIN_POSITION_SHARES,
    BET_SIZE_MAX,
    BET_SIZE_MIN,
    MAX_BUDGET_FRACTION,
    TAKER_FEE_BPS,
    THESIS_MIN_BTC_DISTANCE,
    TRAILING_STOP_GAP,
    log,
)
from math_signal import Signal, _book_implied_p_up, _clip, _norm_cdf
from positions import Position

from .base import PositionDecision, StrategyContext

import exit_gate_ml as _exit_gate_ml

import os as _os

# ── Entry tuning ────────────────────────────────────────────────────────────
SMART_MIN_Z_EARLY = float(_os.getenv("SMART_MIN_Z_EARLY", "1.8"))
SMART_MIN_Z_LATE = float(_os.getenv("SMART_MIN_Z_LATE", "0.8"))
SMART_MIN_EDGE = float(_os.getenv("SMART_MIN_EDGE", "0.03"))
SMART_MIN_BOOK_DIVERGENCE = float(_os.getenv("SMART_MIN_BOOK_DIVERGENCE", "0.03"))
SMART_ENTRY_FLOOR = float(_os.getenv("SMART_ENTRY_FLOOR", "0.30"))
SMART_ENTRY_CEIL = float(_os.getenv("SMART_ENTRY_CEIL", "0.70"))
SMART_LATE_FLOOR = float(_os.getenv("SMART_LATE_FLOOR", "0.15"))
SMART_LATE_CEIL = float(_os.getenv("SMART_LATE_CEIL", "0.88"))
SMART_LATE_BAR_SECS = int(_os.getenv("SMART_LATE_BAR_SECS", "45"))
SMART_LATE_OVERRIDE_Z = float(_os.getenv("SMART_LATE_OVERRIDE_Z", "2.5"))
SMART_ENTRY_MIN_SECONDS_LEFT = int(_os.getenv("SMART_ENTRY_MIN_SECONDS_LEFT", "20"))
SMART_SIZE_Z_REF = float(_os.getenv("SMART_SIZE_Z_REF", "2.0"))
SMART_SIZE_MIN_MULT = float(_os.getenv("SMART_SIZE_MIN_MULT", "0.5"))
SMART_SIZE_MAX_MULT = float(_os.getenv("SMART_SIZE_MAX_MULT", "2.0"))
# Binance staleness gate. If binance_age exceeds this, skip entry (latency edge is gone).
# Late-bar entries (seconds_left < SMART_LATE_BAR_SECS) bypass this gate.
# 0 disables the gate entirely.
SMART_BINANCE_MAX_AGE = float(_os.getenv("SMART_BINANCE_MAX_AGE", "0"))
# Require this many seconds to have elapsed in the bar before entering.
# Early-bar entries have near-full sigma_rem and are usually noise. 0 disables.
SMART_MIN_ELAPSED_SECS = int(_os.getenv("SMART_MIN_ELAPSED_SECS", "0"))
# Probability shrinkage factor applied to raw_p_up. 1.0 = no shrinkage, 0.5 = heavy shrinkage.
SMART_SHRINKAGE = float(_os.getenv("SMART_SHRINKAGE", "0.92"))
# Z-clip applied BEFORE computing p_up. Caps the z fed into norm_cdf so the
# raw probability stays away from extremes. 0 disables (uses existing ±3 clip).
# E.g. 1.5 → raw_p_up bounded to [norm_cdf(-1.5), norm_cdf(+1.5)] = [0.067, 0.933].
# Phase-1 calibration showed model is dramatically over-confident at extreme |z|;
# tighter clip + stronger shrinkage corrects this at the source.
SMART_PUP_Z_CAP = float(_os.getenv("SMART_PUP_Z_CAP", "0"))
# Hard cap on sigma_5m — above this, skip (high vol = unreliable signal). 0 disables.
SMART_MAX_SIGMA = float(_os.getenv("SMART_MAX_SIGMA", "0"))
# Empirical calibration: alpha-blend model p_up toward empirical WR by z-bucket.
# 0 = disabled. 1.0 = fully replace model with empirical WR.
# Empirical WRs from 5-bundle corpus (164 trades): z≥3→82.9%, z≥2.2→61.6%.
SMART_CALIB_ALPHA = float(_os.getenv("SMART_CALIB_ALPHA", "0"))
# If set, evaluate_position always returns empty (pure hold-to-expiry mode, for A/B testing).
SMART_DISABLE_EXITS = _os.getenv("SMART_DISABLE_EXITS", "0") == "1"
# Toggle each exit individually (for ablation). "1" = enabled.
SMART_EXIT_PROFIT_LOCK = _os.getenv("SMART_EXIT_PROFIT_LOCK", "1") == "1"
SMART_EXIT_LATE_SKIM = _os.getenv("SMART_EXIT_LATE_SKIM", "1") == "1"
SMART_EXIT_THESIS_BREAK = _os.getenv("SMART_EXIT_THESIS_BREAK", "1") == "1"
SMART_EXIT_LATE_SALVAGE = _os.getenv("SMART_EXIT_LATE_SALVAGE", "1") == "1"

# ── Exit tuning ─────────────────────────────────────────────────────────────
SMART_PROFIT_LOCK_ARM = float(_os.getenv("SMART_PROFIT_LOCK_ARM", "0.10"))
SMART_PROFIT_LOCK_GAP = float(_os.getenv("SMART_PROFIT_LOCK_GAP", str(TRAILING_STOP_GAP)))
# Conditional profit-lock: only arm when entry was high-conviction.
# SMART_PROFIT_LOCK_MIN_ENTRY_PRICE: require entry_price >= threshold (0 disables).
# SMART_PROFIT_LOCK_MIN_ABS_P: require |entry_p_up - 0.5| >= threshold (0 disables).
SMART_PROFIT_LOCK_MIN_ENTRY_PRICE = float(_os.getenv("SMART_PROFIT_LOCK_MIN_ENTRY_PRICE", "0"))
SMART_PROFIT_LOCK_MIN_ABS_P = float(_os.getenv("SMART_PROFIT_LOCK_MIN_ABS_P", "0"))
SMART_LATE_SKIM_SECS = int(_os.getenv("SMART_LATE_SKIM_SECS", "90"))
SMART_LATE_SKIM_BID = float(_os.getenv("SMART_LATE_SKIM_BID", "0.88"))
SMART_SALVAGE_SECS = int(_os.getenv("SMART_SALVAGE_SECS", "45"))
# Minimum unrealized loss to trigger salvage (default -0.03). More negative = fires less often.
SMART_SALVAGE_MIN_LOSS = float(_os.getenv("SMART_SALVAGE_MIN_LOSS", "-0.03"))
SMART_THESIS_BREAK_SECS = int(_os.getenv("SMART_THESIS_BREAK_SECS", "60"))
SMART_THESIS_BREAK_BTC = float(_os.getenv("SMART_THESIS_BREAK_BTC", str(THESIS_MIN_BTC_DISTANCE)))
# Sigma-aware thesis break: if >0, threshold becomes mult * sigma_5m (scales with realized vol).
# Overrides SMART_THESIS_BREAK_BTC when active.
SMART_THESIS_BREAK_SIGMA_MULT = float(_os.getenv("SMART_THESIS_BREAK_SIGMA_MULT", "0"))
SMART_FORCE_EXIT_SECS = int(_os.getenv("SMART_FORCE_EXIT_SECS", "10"))

# ── Velocity-aware salvage (Phase 1 2026-04-24) ─────────────────────────────
# Fires independent of SMART_SALVAGE_SECS so collapsing-book losers are caught
# before the bid crashes to 0.15.
# Bid-floor: exit immediately if same-side bid drops below this absolute level
# AND position is losing. 0 disables.
SMART_SALVAGE_BID_FLOOR = float(_os.getenv("SMART_SALVAGE_BID_FLOOR", "0"))
# Bid-velocity: exit if bid dropped more than this amount within the window,
# AND position is losing. 0 disables.
SMART_SALVAGE_BID_VELOCITY_DROP = float(_os.getenv("SMART_SALVAGE_BID_VELOCITY_DROP", "0"))
SMART_SALVAGE_BID_VELOCITY_WINDOW = float(_os.getenv("SMART_SALVAGE_BID_VELOCITY_WINDOW", "3"))
# Only fire salvage_floor / salvage_velocity if peak_bid never rose more than
# this above entry — i.e. the position was never meaningfully profitable. Avoids
# stopping out deep-ITM positions on transient bid spikes that revert. 0 disables
# the guard (current behavior).
SMART_SALVAGE_REQUIRE_PEAK_FLAT_MAX = float(_os.getenv("SMART_SALVAGE_REQUIRE_PEAK_FLAT_MAX", "0"))

# In-bar bid history, keyed by (condition_id, direction). Populated on every
# evaluate_position call; pruned beyond the velocity window.
_bid_history: dict[tuple[str, str], list[tuple[float, float]]] = {}

# ── Advanced knobs (all OFF by default) ─────────────────────────────────────
# Size cap: if |z| > cap, clamp size_mult to the value it would have at z=cap.
# Phase-6 diag showed size_lvl=3 (big-z) was negative PnL.
SMART_SIZE_Z_CAP = float(_os.getenv("SMART_SIZE_Z_CAP", "0"))
# Directional divergence: if 1, require sign(p_up - implied) aligned with signal direction.
SMART_DIVERGENCE_DIRECTIONAL = _os.getenv("SMART_DIVERGENCE_DIRECTIONAL", "0") == "1"
# Regime-aware sizing (scales size_mult by BTC recent-drift alignment).
# Uses ctx.ret_60s. Default neutral (both 1.0).
SMART_REGIME_ALIGN = float(_os.getenv("SMART_REGIME_ALIGN", "1.0"))
SMART_REGIME_AGAINST = float(_os.getenv("SMART_REGIME_AGAINST", "1.0"))
SMART_REGIME_MIN_ABS_RET = float(_os.getenv("SMART_REGIME_MIN_ABS_RET", "0.0002"))
# Kelly sizing: if "kelly", size_mult = clamp(edge / sigma_rem_proxy, MIN_MULT, MAX_MULT).
SMART_SIZE_MODE = _os.getenv("SMART_SIZE_MODE", "zscore").lower()  # zscore | kelly
# ML gate: if >0, require predict_entry_score() >= threshold as an additional gate.
SMART_ML_GATE_MIN_P = float(_os.getenv("SMART_ML_GATE_MIN_P", "0"))

# ── Entry-quality gates (Phase 4 2026-04-24) ────────────────────────────────
# All defaults preserve baseline behavior (gates disabled).
# Mid-fair late skip: reject entries where price is in [LO, HI] AND seconds_left
# < SECS. Coin-flip zone where both sides are uncertain and there's too little
# time for a decisive move. Example: entry @ 0.56 w/ 46s left that lost -$8.
# LO >= HI disables the rule.
SMART_SKIP_MIDFAIR_LATE_PRICE_LO = float(_os.getenv("SMART_SKIP_MIDFAIR_LATE_PRICE_LO", "0"))
SMART_SKIP_MIDFAIR_LATE_PRICE_HI = float(_os.getenv("SMART_SKIP_MIDFAIR_LATE_PRICE_HI", "0"))
SMART_SKIP_MIDFAIR_LATE_SECS = int(_os.getenv("SMART_SKIP_MIDFAIR_LATE_SECS", "60"))
# Override: if |z| >= this, don't skip even in mid-fair-late zone (strong signal).
# Matches SMART_LATE_OVERRIDE_Z semantics from the price-band override.
SMART_MIDFAIR_LATE_OVERRIDE_Z = float(_os.getenv("SMART_MIDFAIR_LATE_OVERRIDE_Z", "0"))
# Chase skip: reject if |ret_30s| > threshold AND recent move direction
# matches bet direction (chasing a played-out short-window move). 0 disables.
SMART_SKIP_CHASE_RET = float(_os.getenv("SMART_SKIP_CHASE_RET", "0"))
# Trend-fight skip: reject if |ret_30m| > threshold AND recent move direction
# is OPPOSITE bet direction (fighting a sustained trend; the math model is
# usually contrarian via mean-reversion, so this catches the case where BTC
# trends past the bar threshold and the model keeps insisting on a reversal).
# 30-min window is calibrated to the typical regime-drift timescale; shorter
# windows (5m) miss slow rallies that wreck contrarian DOWN bets. 0 disables.
SMART_SKIP_TRENDFIGHT_RET30M = float(_os.getenv("SMART_SKIP_TRENDFIGHT_RET30M", "0"))
# Stale-chase skip: reject if |ret_30m| > threshold AND move direction MATCHES
# bet direction (chasing an exhausted multi-minute move). Distinct from the
# short-window chase gate (ret_30s tick spike): this catches "BTC trended DOWN
# 30+ bps over 30 min, model still says DOWN, but the move is played out and
# usually reverses." Bundle 20260427_075827 lost ~$32 on three such entries
# (ret_30m −36 / −50 / −20 bp, all DOWN bets). 0 disables.
SMART_SKIP_STALE_CHASE_RET30M = float(_os.getenv("SMART_SKIP_STALE_CHASE_RET30M", "0"))
# Late-bar min edge: require net edge >= LATE_MIN_EDGE when seconds_left <
# LATE_EDGE_SECS. Countervails the strategy's looser _min_z_for() late-bar
# threshold. 0 disables.
SMART_LATE_MIN_EDGE = float(_os.getenv("SMART_LATE_MIN_EDGE", "0"))
SMART_LATE_EDGE_SECS = int(_os.getenv("SMART_LATE_EDGE_SECS", "180"))

# Model-driven exit (Phase 5 2026-04-27). LightGBM classifier predicts
# P(eventual exit beats current bid by >= 0.05). When prob > threshold AND
# we're not in the force-close window, exit at the current bid rather than
# wait for static late_bar_salvage to dump into a collapsed book. Default 0
# disables; set 0.5-0.85 to enable. Training: ai/pm_btc_exit/.
SMART_EXIT_MODEL_THRESHOLD = float(_os.getenv("SMART_EXIT_MODEL_THRESHOLD", "0"))
SMART_EXIT_MODEL_MIN_SECS_LEFT = int(_os.getenv("SMART_EXIT_MODEL_MIN_SECS_LEFT", "30"))
SMART_EXIT_MODEL_MIN_HELD_SECS = int(_os.getenv("SMART_EXIT_MODEL_MIN_HELD_SECS", "5"))


def _min_z_for(seconds_left: int) -> float:
    """Linearly interpolate z-threshold: high early, low late."""
    bar_len = float(BAR_DURATION_SECS)
    sec = max(0, min(seconds_left, int(bar_len)))
    elapsed = 1.0 - sec / bar_len
    return SMART_MIN_Z_EARLY - (SMART_MIN_Z_EARLY - SMART_MIN_Z_LATE) * elapsed


def _price_band(seconds_left: int, z_abs: float) -> tuple[float, float]:
    if seconds_left < SMART_LATE_BAR_SECS and z_abs >= SMART_LATE_OVERRIDE_Z:
        return SMART_LATE_FLOOR, SMART_LATE_CEIL
    return SMART_ENTRY_FLOOR, SMART_ENTRY_CEIL


def _compute_signal(ctx: StrategyContext, *, require_budget: bool) -> Signal:
    def _nope(reason: str, **dbg) -> Signal:
        return Signal(
            action="NO_TRADE",
            price=None,
            size=0,
            p_up=round(dbg.get("p_up", 0.5), 4),
            edge=round(dbg.get("edge", 0.0), 4),
            reason=reason,
            debug=dbg,
        )

    if ctx.seconds_left < SMART_ENTRY_MIN_SECONDS_LEFT:
        return _nope("Too little time left")
    elapsed = BAR_DURATION_SECS - ctx.seconds_left
    if SMART_MIN_ELAPSED_SECS > 0 and elapsed < SMART_MIN_ELAPSED_SECS:
        return _nope(f"Bar too fresh elapsed={elapsed}")
    if ctx.bar_open <= 0 or ctx.current_price <= 0:
        return _nope("Missing BTC prices")
    if SMART_MAX_SIGMA > 0 and ctx.sigma_5m > SMART_MAX_SIGMA:
        return _nope(f"Sigma too high {ctx.sigma_5m:.5f}")
    if (
        SMART_BINANCE_MAX_AGE > 0
        and ctx.seconds_left >= SMART_LATE_BAR_SECS
        and (ctx.binance_price <= 0 or ctx.binance_age > SMART_BINANCE_MAX_AGE)
    ):
        return _nope(f"Binance stale age={ctx.binance_age:.1f}")
    if not (0 < ctx.up_bid <= ctx.up_ask < 1 and 0 < ctx.down_bid <= ctx.down_ask < 1):
        return _nope("Books not live")

    spread_up = ctx.up_ask - ctx.up_bid
    spread_down = ctx.down_ask - ctx.down_bid
    if spread_up > MAX_ENTRY_SPREAD and spread_down > MAX_ENTRY_SPREAD:
        return _nope(f"Spread wide up={spread_up:.3f} dn={spread_down:.3f}")

    best_price = ctx.binance_price if ctx.binance_price > 0 else ctx.current_price
    price_source = "binance" if ctx.binance_price > 0 else "chainlink"

    btc_distance = math.log(best_price / ctx.bar_open)
    time_frac = max(ctx.seconds_left / float(BAR_DURATION_SECS), 1e-6)
    sigma_rem = max(ctx.sigma_5m * math.sqrt(time_frac), 1e-6)
    z = _clip(btc_distance / sigma_rem, -4.0, 4.0)

    min_z = _min_z_for(ctx.seconds_left)
    if abs(z) < min_z:
        return _nope(
            f"z={z:+.2f} below min={min_z:.2f}",
            z=round(z, 3), min_z=round(min_z, 3),
            btc_distance=round(btc_distance, 6), price_source=price_source,
        )

    # Fair probability (same normal model as math_signal, kept local)
    pup_z_clip = SMART_PUP_Z_CAP if SMART_PUP_Z_CAP > 0 else 3.0
    raw_p_up = _norm_cdf(_clip(z, -pup_z_clip, pup_z_clip))
    p_up = 0.5 + SMART_SHRINKAGE * (raw_p_up - 0.5)
    p_up = _clip(p_up, 0.05, 0.95)
    if SMART_CALIB_ALPHA > 0:
        empirical_wr = 0.829 if abs(z) >= 3.0 else 0.616
        p_up = (1.0 - SMART_CALIB_ALPHA) * p_up + SMART_CALIB_ALPHA * empirical_wr
        p_up = _clip(p_up, 0.05, 0.95)
    p_down = 1.0 - p_up
    implied = _book_implied_p_up(ctx.up_bid, ctx.up_ask, ctx.down_bid, ctx.down_ask)
    divergence_signed = p_up - implied  # + means we want UP, - means DOWN
    book_divergence = abs(divergence_signed)
    if book_divergence < SMART_MIN_BOOK_DIVERGENCE:
        return _nope(
            f"Book priced in div={book_divergence:.3f}",
            p_up=p_up, book_divergence=round(book_divergence, 4),
            btc_distance=round(btc_distance, 6), price_source=price_source,
        )

    fee = TAKER_FEE_BPS / 10000.0
    net_up = p_up - ctx.up_ask - fee
    net_down = p_down - ctx.down_ask - fee

    floor, ceil = _price_band(ctx.seconds_left, abs(z))
    up_tradeable = floor <= ctx.up_ask <= ceil and spread_up <= MAX_ENTRY_SPREAD
    down_tradeable = floor <= ctx.down_ask <= ceil and spread_down <= MAX_ENTRY_SPREAD

    dbg = dict(
        z=round(z, 3), min_z=round(min_z, 3),
        p_up=round(p_up, 4), p_down=round(p_down, 4),
        net_up=round(net_up, 4), net_down=round(net_down, 4),
        seconds_left=ctx.seconds_left,
        btc_distance=round(btc_distance, 6),
        price_source=price_source,
        book_divergence=round(book_divergence, 4),
        floor=floor, ceil=ceil,
        sigma_5m=round(ctx.sigma_5m, 6),
    )

    if net_up >= net_down and net_up >= SMART_MIN_EDGE and up_tradeable:
        action, price, p, edge = "BUY_UP", ctx.up_ask, p_up, net_up
        direction_sign = 1.0
    elif net_down > net_up and net_down >= SMART_MIN_EDGE and down_tradeable:
        action, price, p, edge = "BUY_DOWN", ctx.down_ask, p_down, net_down
        direction_sign = -1.0
    else:
        reason = f"No edge above {SMART_MIN_EDGE:.3f}"
        if net_up >= SMART_MIN_EDGE and not up_tradeable:
            reason = f"UP outside band ask={ctx.up_ask:.3f}"
        elif net_down >= SMART_MIN_EDGE and not down_tradeable:
            reason = f"DOWN outside band ask={ctx.down_ask:.3f}"
        return _nope(reason, edge=max(net_up, net_down), **dbg)

    # Phase 4 entry-quality gates. All default-off; preserve baseline behavior.
    if (
        SMART_SKIP_MIDFAIR_LATE_PRICE_LO < SMART_SKIP_MIDFAIR_LATE_PRICE_HI
        and SMART_SKIP_MIDFAIR_LATE_PRICE_LO <= price <= SMART_SKIP_MIDFAIR_LATE_PRICE_HI
        and ctx.seconds_left < SMART_SKIP_MIDFAIR_LATE_SECS
        and not (SMART_MIDFAIR_LATE_OVERRIDE_Z > 0 and abs(z) >= SMART_MIDFAIR_LATE_OVERRIDE_Z)
    ):
        return _nope(
            f"Midfair-late skip price={price:.2f} secs={ctx.seconds_left} z={z:+.2f}",
            edge=edge, **dbg,
        )

    if SMART_SKIP_CHASE_RET > 0:
        ret30 = getattr(ctx, "ret_30s", 0.0) or 0.0
        if abs(ret30) > SMART_SKIP_CHASE_RET:
            move_sign = 1.0 if ret30 > 0 else -1.0
            # Chasing: bet direction matches the recent move (betting it continues)
            if move_sign * direction_sign > 0:
                return _nope(
                    f"Chase skip ret30={ret30:+.4f} dir={action}",
                    edge=edge, **dbg,
                )

    if SMART_SKIP_TRENDFIGHT_RET30M > 0 or SMART_SKIP_STALE_CHASE_RET30M > 0:
        ret30m = getattr(ctx, "ret_30m", 0.0) or 0.0
        abs_ret30m = abs(ret30m)
        if abs_ret30m > 0:
            move_sign = 1.0 if ret30m > 0 else -1.0
            # Trend-fight: bet direction OPPOSES the recent 30-min move
            if (
                SMART_SKIP_TRENDFIGHT_RET30M > 0
                and abs_ret30m > SMART_SKIP_TRENDFIGHT_RET30M
                and move_sign * direction_sign < 0
            ):
                return _nope(
                    f"Trend-fight skip ret30m={ret30m:+.4f} dir={action}",
                    edge=edge, **dbg,
                )
            # Stale-chase: bet direction MATCHES a played-out 30-min move
            if (
                SMART_SKIP_STALE_CHASE_RET30M > 0
                and abs_ret30m > SMART_SKIP_STALE_CHASE_RET30M
                and move_sign * direction_sign > 0
            ):
                return _nope(
                    f"Stale-chase skip ret30m={ret30m:+.4f} dir={action}",
                    edge=edge, **dbg,
                )

    if (
        SMART_LATE_MIN_EDGE > 0
        and ctx.seconds_left < SMART_LATE_EDGE_SECS
        and edge < SMART_LATE_MIN_EDGE
    ):
        return _nope(
            f"Late-edge floor edge={edge:.3f} < {SMART_LATE_MIN_EDGE:.3f} @ secs={ctx.seconds_left}",
            edge=edge, **dbg,
        )

    if SMART_DIVERGENCE_DIRECTIONAL and divergence_signed * direction_sign < 0:
        return _nope(
            f"Divergence against dir div={divergence_signed:+.3f} dir={action}",
            edge=edge, **dbg,
        )

    if SMART_ML_GATE_MIN_P > 0:
        try:
            from entry_gate_ml import predict_entry_score as _ml_score
            preview = Signal(
                action=action, price=round(price, 4), size=0,
                p_up=round(p_up, 4), edge=round(edge, 4), reason="ml_preview",
                debug=dbg,
            )
            ml_p = _ml_score(ctx, preview)
            if ml_p is not None and ml_p < SMART_ML_GATE_MIN_P:
                return _nope(
                    f"ML gate p={ml_p:.3f} < {SMART_ML_GATE_MIN_P:.3f}",
                    edge=edge, ml_p=round(ml_p, 4), **dbg,
                )
            if ml_p is not None:
                dbg["ml_p"] = round(ml_p, 4)
        except Exception as e:
            dbg["ml_error"] = str(e)[:60]

    if not require_budget:
        return Signal(
            action=action, price=round(price, 4), size=0,
            p_up=round(p_up, 4), edge=round(edge, 4),
            reason=f"z={z:+.2f} fair={p:.3f} mkt={price:.3f} edge={edge:.4f} div={book_divergence:.3f}",
            debug=dbg,
        )

    if SMART_SIZE_MODE == "kelly":
        # Kelly for a binary bet: f* = edge / (price * (1-price)). Use p (our side prob).
        variance = max(p * (1.0 - p), 1e-3)
        kelly_raw = edge / variance
        size_mult = _clip(kelly_raw, SMART_SIZE_MIN_MULT, SMART_SIZE_MAX_MULT)
    else:
        z_for_size = abs(z)
        if SMART_SIZE_Z_CAP > 0 and z_for_size > SMART_SIZE_Z_CAP:
            z_for_size = SMART_SIZE_Z_CAP
        size_mult = _clip(z_for_size / SMART_SIZE_Z_REF, SMART_SIZE_MIN_MULT, SMART_SIZE_MAX_MULT)

    if SMART_REGIME_ALIGN != 1.0 or SMART_REGIME_AGAINST != 1.0:
        ret_60 = getattr(ctx, "ret_60s", 0.0) or 0.0
        if abs(ret_60) >= SMART_REGIME_MIN_ABS_RET:
            regime_sign = 1.0 if ret_60 > 0 else -1.0
            if regime_sign * direction_sign > 0:
                size_mult *= SMART_REGIME_ALIGN
            else:
                size_mult *= SMART_REGIME_AGAINST
            size_mult = _clip(size_mult, SMART_SIZE_MIN_MULT, SMART_SIZE_MAX_MULT)

    budget_cap = min(ctx.cash_amount * MAX_BUDGET_FRACTION, BET_SIZE_MAX)
    budget = min(budget_cap * size_mult, BET_SIZE_MAX)
    if budget < BET_SIZE_MIN:
        return _nope(f"Budget {budget:.3f} < min {BET_SIZE_MIN:.3f}", edge=edge, **dbg)
    shares = int(math.floor(budget / price))
    if shares < MIN_POSITION_SHARES:
        return _nope(f"Shares {shares} < min {MIN_POSITION_SHARES}", edge=edge, shares=shares, **dbg)

    dbg["size_mult"] = round(size_mult, 3)
    return Signal(
        action=action, price=round(price, 4), size=shares,
        p_up=round(p_up, 4), edge=round(edge, 4),
        reason=f"z={z:+.2f} fair={p:.3f} mkt={price:.3f} edge={edge:.4f} div={book_divergence:.3f} src={price_source}",
        debug=dbg,
    )


class MathSmartStrategy:
    name = "math_smart"

    def startup_details(self) -> list[str]:
        return [
            f"STRATEGY={self.name}",
            f"ENTRY_MODE={self.entry_order_mode()}",
            f"Z_EARLY={SMART_MIN_Z_EARLY:.2f} Z_LATE={SMART_MIN_Z_LATE:.2f} MIN_EDGE={SMART_MIN_EDGE:.3f}",
            f"BAND=[{SMART_ENTRY_FLOOR:.2f},{SMART_ENTRY_CEIL:.2f}] LATE=[{SMART_LATE_FLOOR:.2f},{SMART_LATE_CEIL:.2f}]",
            f"THESIS_BREAK_BTC={SMART_THESIS_BREAK_BTC:.4f} LATE_SKIM@{SMART_LATE_SKIM_BID:.2f}<{SMART_LATE_SKIM_SECS}s",
        ]

    def entry_order_mode(self) -> str:
        return ENTRY_ORDER_MODE

    def entry_hold_to_expiry(self) -> bool:
        # We may exit early on thesis break / profit lock. main.py uses this
        # only to decide whether to post the $0.99 GTC sell immediately; we
        # want active management, so return False.
        return False

    def evaluate_entry(self, ctx: StrategyContext) -> Signal:
        return _compute_signal(ctx, require_budget=True)

    def evaluate_position(
        self,
        ctx: StrategyContext,
        pos: Position,
        current_bid: float,
        now: float,
    ) -> PositionDecision:
        if SMART_DISABLE_EXITS:
            return PositionDecision()
        unrealized = current_bid - pos.entry_price
        btc_distance = (
            math.log(ctx.current_price / ctx.bar_open) if ctx.bar_open > 0 and ctx.current_price > 0 else 0.0
        )
        thesis_alive = (
            (pos.direction == "UP" and btc_distance > 0)
            or (pos.direction == "DOWN" and btc_distance < 0)
        )
        adverse_btc = -btc_distance if pos.direction == "UP" else btc_distance

        # 1. Force exit in final seconds regardless of state.
        if ctx.seconds_left <= SMART_FORCE_EXIT_SECS:
            log.info(
                "SMART_FORCE_EXIT  secs=%d bid=%.4f entry=%.4f pnl=%+.4f",
                ctx.seconds_left, current_bid, pos.entry_price, unrealized,
            )
            return PositionDecision(exit_reason="force_close")

        # 2. Late-bar skim: pocket near-resolution profit rather than risk flip.
        if (
            SMART_EXIT_LATE_SKIM
            and ctx.seconds_left < SMART_LATE_SKIM_SECS
            and current_bid >= SMART_LATE_SKIM_BID
            and not pos.sell_order_id
        ):
            log.info(
                "SMART_LATE_SKIM  secs=%d bid=%.4f entry=%.4f pnl=%+.4f",
                ctx.seconds_left, current_bid, pos.entry_price, unrealized,
            )
            return PositionDecision(exit_reason="late_bar_skim")

        # 3. Profit-lock trailing once we're comfortably ahead.
        profit_lock_gated_out = (
            (SMART_PROFIT_LOCK_MIN_ENTRY_PRICE > 0 and pos.entry_price < SMART_PROFIT_LOCK_MIN_ENTRY_PRICE)
            or (SMART_PROFIT_LOCK_MIN_ABS_P > 0 and abs(pos.entry_p_up - 0.5) < SMART_PROFIT_LOCK_MIN_ABS_P)
        )
        if (
            SMART_EXIT_PROFIT_LOCK
            and not profit_lock_gated_out
            and pos.peak_bid >= pos.entry_price + SMART_PROFIT_LOCK_ARM
        ):
            if (
                current_bid <= pos.peak_bid - SMART_PROFIT_LOCK_GAP
                and current_bid > pos.entry_price
                and not pos.sell_order_id
            ):
                log.info(
                    "SMART_PROFIT_LOCK  bid=%.4f peak=%.4f entry=%.4f",
                    current_bid, pos.peak_bid, pos.entry_price,
                )
                return PositionDecision(exit_reason="profit_lock_trail")

        # 3a. Model-driven exit (Phase 5 2026-04-27).
        # Run BEFORE the static velocity/late salvage so the model can dump
        # earlier when bid is still 0.40-0.50 instead of waiting for the static
        # trigger at <45s left where bid has often collapsed to 0.05-0.20.
        if (
            SMART_EXIT_MODEL_THRESHOLD > 0
            and not pos.sell_order_id
            and ctx.seconds_left > SMART_EXIT_MODEL_MIN_SECS_LEFT
        ):
            entry_secs = int(getattr(pos, "entry_seconds_left", BAR_DURATION_SECS) or BAR_DURATION_SECS)
            held = max(0, entry_secs - ctx.seconds_left)
            if held >= SMART_EXIT_MODEL_MIN_HELD_SECS:
                p_loss = _exit_gate_ml.predict_loss_prob(
                    ctx, pos, current_bid, now, btc_distance, adverse_btc,
                )
                if p_loss is not None and p_loss > SMART_EXIT_MODEL_THRESHOLD:
                    log.info(
                        "SMART_MODEL_EXIT  p_loss=%.3f thr=%.2f bid=%.4f entry=%.4f secs=%d held=%ds",
                        p_loss, SMART_EXIT_MODEL_THRESHOLD, current_bid,
                        pos.entry_price, ctx.seconds_left, held,
                    )
                    return PositionDecision(exit_reason="model_exit")

        # 3b. Velocity-aware salvage (Phase 1 2026-04-24).
        # Runs regardless of seconds_left — catches collapsing books BEFORE the
        # existing late-bar salvage at sec<45, which was exiting at 0.05-0.30.
        # Gated on `not thesis_alive` (same as late_bar_salvage) to avoid cutting
        # winners whose bid briefly dips while BTC still supports the position.
        peak_flat = (
            SMART_SALVAGE_REQUIRE_PEAK_FLAT_MAX <= 0
            or (pos.peak_bid - pos.entry_price) <= SMART_SALVAGE_REQUIRE_PEAK_FLAT_MAX
        )
        if (
            (SMART_SALVAGE_BID_FLOOR > 0 or SMART_SALVAGE_BID_VELOCITY_DROP > 0)
            and not thesis_alive
            and unrealized < SMART_SALVAGE_MIN_LOSS
            and peak_flat
            and not pos.sell_order_id
        ):
            key = (pos.condition_id, pos.direction)
            hist = _bid_history.setdefault(key, [])
            hist.append((now, current_bid))
            cutoff_prune = now - max(SMART_SALVAGE_BID_VELOCITY_WINDOW, 10.0)
            while hist and hist[0][0] < cutoff_prune:
                hist.pop(0)

            if SMART_SALVAGE_BID_FLOOR > 0 and current_bid < SMART_SALVAGE_BID_FLOOR:
                log.info(
                    "SMART_SALVAGE_FLOOR  secs=%d bid=%.4f floor=%.4f entry=%.4f pnl=%+.4f",
                    ctx.seconds_left, current_bid, SMART_SALVAGE_BID_FLOOR, pos.entry_price, unrealized,
                )
                _bid_history.pop(key, None)
                return PositionDecision(exit_reason="salvage_floor")

            if SMART_SALVAGE_BID_VELOCITY_DROP > 0:
                cutoff_vel = now - SMART_SALVAGE_BID_VELOCITY_WINDOW
                past_max = current_bid
                for ts_h, bid_h in hist:
                    if ts_h >= cutoff_vel and bid_h > past_max:
                        past_max = bid_h
                drop = past_max - current_bid
                if drop > SMART_SALVAGE_BID_VELOCITY_DROP:
                    log.info(
                        "SMART_SALVAGE_VELOCITY  secs=%d bid=%.4f past_max=%.4f drop=%+.4f window=%.1fs entry=%.4f pnl=%+.4f",
                        ctx.seconds_left, current_bid, past_max, drop, SMART_SALVAGE_BID_VELOCITY_WINDOW,
                        pos.entry_price, unrealized,
                    )
                    _bid_history.pop(key, None)
                    return PositionDecision(exit_reason="salvage_velocity")

        # 4. Thesis break — BTC turned against us meaningfully with time left.
        if SMART_THESIS_BREAK_SIGMA_MULT > 0 and ctx.sigma_5m > 0:
            thesis_break_threshold = SMART_THESIS_BREAK_SIGMA_MULT * ctx.sigma_5m
        else:
            thesis_break_threshold = SMART_THESIS_BREAK_BTC
        if (
            SMART_EXIT_THESIS_BREAK
            and ctx.seconds_left > SMART_THESIS_BREAK_SECS
            and adverse_btc > thesis_break_threshold
            and not pos.sell_order_id
        ):
            log.info(
                "SMART_THESIS_BREAK  dir=%s adv_btc=%+.4f secs=%d bid=%.4f entry=%.4f",
                pos.direction, adverse_btc, ctx.seconds_left, current_bid, pos.entry_price,
            )
            return PositionDecision(exit_reason="thesis_break")

        # 5. Late-bar salvage — close <SALVAGE secs with thesis dead and losing.
        if (
            SMART_EXIT_LATE_SALVAGE
            and ctx.seconds_left < SMART_SALVAGE_SECS
            and not thesis_alive
            and unrealized < SMART_SALVAGE_MIN_LOSS
            and not pos.sell_order_id
        ):
            log.info(
                "SMART_LATE_SALVAGE  secs=%d bid=%.4f entry=%.4f pnl=%+.4f adv=%+.4f",
                ctx.seconds_left, current_bid, pos.entry_price, unrealized, adverse_btc,
            )
            return PositionDecision(exit_reason="late_bar_salvage")

        # Otherwise hold.
        return PositionDecision()