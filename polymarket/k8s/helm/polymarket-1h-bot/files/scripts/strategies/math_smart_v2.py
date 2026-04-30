"""math_smart v2 — oracle-forecast entries via Binance + Chainlink basis EMA.

Motivation
----------
Polymarket's RTDS Chainlink feed is ~block-propagation-lagged vs the Binance
top-of-book tape. v1 used `binance_price` directly as the reference for z-score
and book-divergence, which implicitly assumes zero basis between Binance global
and the Chainlink BTC/USD feed Polymarket settles on. In practice the basis
drifts tens of dollars and matters near decision boundaries.

v2 predicts "where Chainlink will be at settlement" by combining:
    forecast = binance_now + EMA(chainlink_recent - binance_recent)

All entry/exit plumbing is inherited from v1; only the reference price used for
`btc_distance` / z-score changes, plus a small number of v2-specific knobs.

Tunables (env-var prefix SMART_V2_*; v1 SMART_* values still apply):

  SMART_V2_BASIS_EMA_ALPHA   EMA smoothing on per-tick basis. Default 0.20.
  SMART_V2_BASIS_WINDOW      Max prior snapshots to scan for basis samples. 120.
  SMART_V2_BASIS_MIN_SAMPLES Need this many samples before trusting the basis. 5.
  SMART_V2_BASIS_MAX_ABS     Cap |basis| used in forecast — prevents a bad
                             sample blowing up the forecast. Default $50.
"""
from __future__ import annotations

import math
import os as _os

from config import (
    BAR_DURATION_SECS,
    ENTRY_ORDER_MODE,
    MAX_ENTRY_SPREAD,
    MIN_POSITION_SHARES,
    BET_SIZE_MAX,
    BET_SIZE_MIN,
    MAX_BUDGET_FRACTION,
    TAKER_FEE_BPS,
    log,
)
from math_signal import Signal, _book_implied_p_up, _clip, _norm_cdf
from positions import Position

from .base import PositionDecision, StrategyContext
from .math_smart import (
    MathSmartStrategy,
    SMART_BINANCE_MAX_AGE,
    SMART_DIVERGENCE_DIRECTIONAL,
    SMART_ENTRY_FLOOR,
    SMART_ENTRY_CEIL,
    SMART_ENTRY_MIN_SECONDS_LEFT,
    SMART_LATE_BAR_SECS,
    SMART_LATE_CEIL,
    SMART_LATE_FLOOR,
    SMART_LATE_OVERRIDE_Z,
    SMART_MAX_SIGMA,
    SMART_MIN_BOOK_DIVERGENCE,
    SMART_MIN_EDGE,
    SMART_MIN_ELAPSED_SECS,
    SMART_MIN_Z_EARLY,
    SMART_MIN_Z_LATE,
    SMART_ML_GATE_MIN_P,
    SMART_REGIME_AGAINST,
    SMART_REGIME_ALIGN,
    SMART_REGIME_MIN_ABS_RET,
    SMART_SHRINKAGE,
    SMART_SIZE_MAX_MULT,
    SMART_SIZE_MIN_MULT,
    SMART_SIZE_MODE,
    SMART_SIZE_Z_CAP,
    SMART_SIZE_Z_REF,
    _min_z_for,
    _price_band,
)

# ── v2-only knobs ───────────────────────────────────────────────────────────
# Mode selects how the basis signal is consumed:
#   forecast     — replace reference price with binance + basis_ema (original v2)
#   haircut      — keep v1 signal; penalise adverse-basis entries (default)
#   chainlink_ref — use current_price (Chainlink) instead of binance as reference
SMART_V2_MODE = _os.getenv("SMART_V2_MODE", "haircut").lower()
SMART_V2_BASIS_EMA_ALPHA = float(_os.getenv("SMART_V2_BASIS_EMA_ALPHA", "0.20"))
SMART_V2_BASIS_WINDOW = int(_os.getenv("SMART_V2_BASIS_WINDOW", "120"))
SMART_V2_BASIS_MIN_SAMPLES = int(_os.getenv("SMART_V2_BASIS_MIN_SAMPLES", "5"))
SMART_V2_BASIS_MAX_ABS = float(_os.getenv("SMART_V2_BASIS_MAX_ABS", "50.0"))

# haircut-mode knobs
SMART_V2_BASIS_ADVERSE_USD = float(_os.getenv("SMART_V2_BASIS_ADVERSE_USD", "5.0"))
SMART_V2_ADVERSE_EDGE_PENALTY = float(_os.getenv("SMART_V2_ADVERSE_EDGE_PENALTY", "0.02"))
SMART_V2_ADVERSE_SIZE_MULT = float(_os.getenv("SMART_V2_ADVERSE_SIZE_MULT", "0.5"))


def _basis_ema(ctx: StrategyContext) -> tuple[float, int]:
    """Return (basis_ema_dollars, samples) using prior + current snapshot.

    basis = chainlink_price - binance_price, aggregated as an EMA over the
    most recent SMART_V2_BASIS_WINDOW snapshots that have both feeds.
    """
    alpha = max(1e-3, min(1.0, SMART_V2_BASIS_EMA_ALPHA))
    ema: float | None = None
    samples = 0
    window = SMART_V2_BASIS_WINDOW
    prior = ctx.prior_snapshots[-window:] if window > 0 else ctx.prior_snapshots
    for snap in prior:
        if not isinstance(snap, dict):
            continue
        btc = snap.get("btc") or {}
        try:
            cl = float(btc.get("current_price") or 0.0)
            bn = float(btc.get("binance_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if cl <= 0 or bn <= 0:
            continue
        basis = cl - bn
        ema = basis if ema is None else alpha * basis + (1.0 - alpha) * ema
        samples += 1
    # Fold in the current tick
    if ctx.current_price > 0 and ctx.binance_price > 0:
        basis = ctx.current_price - ctx.binance_price
        ema = basis if ema is None else alpha * basis + (1.0 - alpha) * ema
        samples += 1
    if ema is None:
        return 0.0, 0
    if SMART_V2_BASIS_MAX_ABS > 0:
        ema = _clip(ema, -SMART_V2_BASIS_MAX_ABS, SMART_V2_BASIS_MAX_ABS)
    return ema, samples


def _reference_price(ctx: StrategyContext) -> tuple[float, str, float, int]:
    """Return (reference_price, source_label, basis_ema, basis_samples).

    Dispatch by SMART_V2_MODE:
      forecast      — binance + basis_ema when enough samples, else binance.
      chainlink_ref — current_price (Chainlink) when live; fall back to binance.
      haircut       — binance (v1 behaviour); basis only used by downstream gates.
    All modes fall back to current_price if binance is unusable.
    """
    basis, samples = _basis_ema(ctx)
    if SMART_V2_MODE == "forecast":
        if ctx.binance_price > 0 and samples >= SMART_V2_BASIS_MIN_SAMPLES:
            return ctx.binance_price + basis, "binance+basis", basis, samples
        if ctx.binance_price > 0:
            return ctx.binance_price, "binance", basis, samples
        return ctx.current_price, "chainlink", basis, samples
    if SMART_V2_MODE == "chainlink_ref":
        if ctx.current_price > 0:
            return ctx.current_price, "chainlink", basis, samples
        return ctx.binance_price, "binance", basis, samples
    # haircut (default) — v1 reference
    if ctx.binance_price > 0:
        return ctx.binance_price, "binance", basis, samples
    return ctx.current_price, "chainlink", basis, samples


def _adverse_basis(direction_sign: float, basis_ema: float, samples: int) -> bool:
    """True when the basis is against the signal direction by >= threshold.

    direction_sign: +1 for BUY_UP, -1 for BUY_DOWN.
    basis = chainlink - binance. basis<0 adverse to UP (oracle lagging low),
    basis>0 adverse to DOWN (oracle lagging high).
    """
    if samples < SMART_V2_BASIS_MIN_SAMPLES:
        return False
    if SMART_V2_BASIS_ADVERSE_USD <= 0:
        return False
    if direction_sign > 0:
        return basis_ema <= -SMART_V2_BASIS_ADVERSE_USD
    return basis_ema >= SMART_V2_BASIS_ADVERSE_USD


def _compute_signal_v2(ctx: StrategyContext, *, require_budget: bool) -> Signal:
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

    best_price, price_source, basis_ema, basis_samples = _reference_price(ctx)
    if best_price <= 0:
        return _nope("No usable reference price")

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
            basis_ema=round(basis_ema, 3), basis_samples=basis_samples,
        )

    raw_p_up = _norm_cdf(_clip(z, -3.0, 3.0))
    p_up = 0.5 + SMART_SHRINKAGE * (raw_p_up - 0.5)
    p_up = _clip(p_up, 0.05, 0.95)
    p_down = 1.0 - p_up
    implied = _book_implied_p_up(ctx.up_bid, ctx.up_ask, ctx.down_bid, ctx.down_ask)
    divergence_signed = p_up - implied
    book_divergence = abs(divergence_signed)
    if book_divergence < SMART_MIN_BOOK_DIVERGENCE:
        return _nope(
            f"Book priced in div={book_divergence:.3f}",
            p_up=p_up, book_divergence=round(book_divergence, 4),
            btc_distance=round(btc_distance, 6), price_source=price_source,
            basis_ema=round(basis_ema, 3), basis_samples=basis_samples,
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
        basis_ema=round(basis_ema, 3),
        basis_samples=basis_samples,
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

    if SMART_DIVERGENCE_DIRECTIONAL and divergence_signed * direction_sign < 0:
        return _nope(
            f"Divergence against dir div={divergence_signed:+.3f} dir={action}",
            edge=edge, **dbg,
        )

    adverse = _adverse_basis(direction_sign, basis_ema, basis_samples)
    dbg["basis_adverse"] = bool(adverse)
    size_penalty = 1.0
    if adverse:
        required = SMART_MIN_EDGE + SMART_V2_ADVERSE_EDGE_PENALTY
        if edge < required:
            return _nope(
                f"Basis adverse basis={basis_ema:+.2f} need_edge>={required:.3f}",
                edge=edge, **dbg,
            )
        size_penalty = SMART_V2_ADVERSE_SIZE_MULT

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
            reason=f"z={z:+.2f} fair={p:.3f} mkt={price:.3f} edge={edge:.4f} div={book_divergence:.3f} src={price_source} basis={basis_ema:+.2f}",
            debug=dbg,
        )

    if SMART_SIZE_MODE == "kelly":
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

    if size_penalty != 1.0:
        size_mult = _clip(size_mult * size_penalty, SMART_SIZE_MIN_MULT, SMART_SIZE_MAX_MULT)

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
        reason=f"z={z:+.2f} fair={p:.3f} mkt={price:.3f} edge={edge:.4f} div={book_divergence:.3f} src={price_source} basis={basis_ema:+.2f} n={basis_samples}",
        debug=dbg,
    )


class MathSmartV2Strategy(MathSmartStrategy):
    """v2 overrides only the entry-price forecast. Exits inherit from v1."""

    name = "math_smart_v2"

    def startup_details(self) -> list[str]:
        details = list(super().startup_details())
        details[0] = f"STRATEGY={self.name}"
        details.append(
            f"V2 mode={SMART_V2_MODE} ema_alpha={SMART_V2_BASIS_EMA_ALPHA:.2f} "
            f"window={SMART_V2_BASIS_WINDOW} min_samples={SMART_V2_BASIS_MIN_SAMPLES} "
            f"cap=${SMART_V2_BASIS_MAX_ABS:.0f} adverse_usd=${SMART_V2_BASIS_ADVERSE_USD:.1f} "
            f"edge_pen={SMART_V2_ADVERSE_EDGE_PENALTY:.3f} size_mult={SMART_V2_ADVERSE_SIZE_MULT:.2f}"
        )
        return details

    def evaluate_entry(self, ctx: StrategyContext) -> Signal:
        return _compute_signal_v2(ctx, require_budget=True)
