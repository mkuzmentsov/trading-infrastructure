"""
Mathematical signal generation — no AI/ML.

Models the remaining BTC move as a normal log-return:

  log(S_T) ~ Normal(log(S) + μ_rem, σ_rem²)

So:

  p_up = Φ((log(S) + μ_rem - log(O)) / σ_rem)

Edge is computed conservatively: model probability minus current ask minus a
round-trip trading cost estimate. The probability is shrunk back toward 50% to
avoid overconfidence from noisy microstructure inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from config import (
    BET_SIZE_MAX,
    BET_SIZE_MIN,
    COST_BUFFER,
    DRIFT_A1,
    DRIFT_A2,
    DRIFT_A3,
    DRIFT_A4,
    EARLY_BAR_MIN_CONFIDENCE,
    EARLY_BAR_RAMP_SECS,
    KELLY_SCALE,
    MAX_ABS_DRIFT,
    MAX_ENTRY_SPREAD,
    MAX_ENTRY_PRICE,
    MIN_EDGE,
    MIN_POSITION_SHARES,
    MODEL_PROB_CEIL,
    MODEL_PROB_FLOOR,
    MODEL_PROB_SHRINK,
    SOURCE_MISMATCH_BUFFER,
)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def book_imbalance(bid_vol: float, ask_vol: float) -> float:
    total = bid_vol + ask_vol
    return (bid_vol - ask_vol) / total if total > 0 else 0.0


def estimate_remaining_drift(
    seconds_left: int,
    ret_30s: float,
    ret_60s: float,
    distance_from_open: float,
    imbalance: float,
) -> float:
    time_frac = seconds_left / 300.0
    raw = (
        DRIFT_A1 * ret_30s
        + DRIFT_A2 * ret_60s
        + DRIFT_A3 * imbalance
        + DRIFT_A4 * distance_from_open
    )
    return _clip(time_frac * raw, -MAX_ABS_DRIFT, MAX_ABS_DRIFT)


def estimate_remaining_sigma(seconds_left: int, sigma_5m: float) -> float:
    time_frac = max(seconds_left / 300.0, 1e-6)
    return max(sigma_5m * math.sqrt(time_frac), 1e-6)


def early_bar_confidence_scale(seconds_left: int) -> float:
    elapsed = _clip(300 - seconds_left, 0, 300)
    ramp = max(EARLY_BAR_RAMP_SECS, 1)
    progress = min(elapsed / ramp, 1.0)
    return _clip(
        EARLY_BAR_MIN_CONFIDENCE + (1.0 - EARLY_BAR_MIN_CONFIDENCE) * progress,
        0.0,
        1.0,
    )


def fair_probability_up(
    open_price: float,
    current_price: float,
    mu_rem: float,
    sigma_rem: float,
    confidence_scale: float,
) -> float:
    if open_price <= 0 or current_price <= 0:
        return 0.5
    z = (math.log(current_price) + mu_rem - math.log(open_price)) / sigma_rem
    z = _clip(z, -0.95, 0.95)
    raw_p = _norm_cdf(z)
    effective_shrink = MODEL_PROB_SHRINK * _clip(confidence_scale, 0.0, 1.0)
    shrunk = 0.5 + effective_shrink * (raw_p - 0.5)
    return _clip(shrunk, MODEL_PROB_FLOOR, MODEL_PROB_CEIL)


def kelly_fraction(p: float, c: float) -> float:
    if c >= 1.0:
        return 0.0
    return max(0.0, (p - c) / (1.0 - c))


def _round_trip_cost(bid: float, ask: float) -> float:
    spread = max(0.0, ask - bid)
    # Conservative all-in cost proxy: entry spread + some exit concession +
    # an optional buffer for any residual source/latency mismatch.
    return max(COST_BUFFER, spread + max(0.01, spread / 2.0) + SOURCE_MISMATCH_BUFFER)


@dataclass
class Signal:
    action: str
    price: Optional[float]
    size: int
    p_up: float
    edge: float
    reason: str
    debug: dict = field(default_factory=dict)


def generate_signal(
    cash_amount: float,
    seconds_left: int,
    bar_open: float,
    current_price: float,
    ret_30s: float,
    ret_60s: float,
    bid_vol_top: float,
    ask_vol_top: float,
    sigma_5m: float,
    up_bid: float,
    up_ask: float,
    down_bid: float,
    down_ask: float,
) -> Signal:
    def _no_trade(reason: str, **kw) -> Signal:
        return Signal(
            action="NO_TRADE",
            price=None,
            size=0,
            p_up=0.5,
            edge=0.0,
            reason=reason,
            debug=kw,
        )

    if seconds_left < 10:
        return _no_trade("Too little time left")

    if bar_open <= 0 or current_price <= 0:
        return _no_trade("Missing BTC prices")

    if not (0 < up_bid <= up_ask < 1 and 0 < down_bid <= down_ask < 1):
        return _no_trade("Books not live")

    spread_up = up_ask - up_bid
    spread_down = down_ask - down_bid
    if spread_up > MAX_ENTRY_SPREAD and spread_down > MAX_ENTRY_SPREAD:
        return _no_trade(
            f"Spread too wide (up={spread_up:.3f}, down={spread_down:.3f})",
            spread_up=round(spread_up, 4),
            spread_down=round(spread_down, 4),
        )

    imbalance = book_imbalance(bid_vol_top, ask_vol_top)
    distance = math.log(current_price / bar_open)

    mu_rem = estimate_remaining_drift(seconds_left, ret_30s, ret_60s, distance, imbalance)
    sigma_rem = estimate_remaining_sigma(seconds_left, sigma_5m)
    confidence_scale = early_bar_confidence_scale(seconds_left)
    p_up = fair_probability_up(bar_open, current_price, mu_rem, sigma_rem, confidence_scale)
    p_down = 1.0 - p_up

    cost_up = _round_trip_cost(up_bid, up_ask)
    cost_down = _round_trip_cost(down_bid, down_ask)
    net_up = p_up - up_ask - cost_up
    net_down = p_down - down_ask - cost_down

    dbg = dict(
        p_up=round(p_up, 4),
        p_down=round(p_down, 4),
        net_up=round(net_up, 4),
        net_down=round(net_down, 4),
        mu_rem=round(mu_rem, 6),
        sigma_rem=round(sigma_rem, 6),
        imbalance=round(imbalance, 4),
        distance=round(distance, 6),
        seconds_left=seconds_left,
        confidence_scale=round(confidence_scale, 4),
        spread_up=round(spread_up, 4),
        spread_down=round(spread_down, 4),
        cost_up=round(cost_up, 4),
        cost_down=round(cost_down, 4),
    )

    up_tradeable = 0.05 <= up_ask <= 0.95 and spread_up <= MAX_ENTRY_SPREAD
    down_tradeable = 0.05 <= down_ask <= 0.95 and spread_down <= MAX_ENTRY_SPREAD
    if up_tradeable and up_ask > MAX_ENTRY_PRICE:
        up_tradeable = False
    if down_tradeable and down_ask > MAX_ENTRY_PRICE:
        down_tradeable = False

    if net_up >= net_down and net_up >= MIN_EDGE and up_tradeable:
        action, price, p, edge = "BUY_UP", up_ask, p_up, net_up
    elif net_down > net_up and net_down >= MIN_EDGE and down_tradeable:
        action, price, p, edge = "BUY_DOWN", down_ask, p_down, net_down
    else:
        reason = "No edge above threshold"
        if net_up >= MIN_EDGE and not up_tradeable:
            reason = f"UP token not tradeable (ask={up_ask:.3f}, spread={spread_up:.3f}, cap={MAX_ENTRY_PRICE:.3f})"
        elif net_down >= MIN_EDGE and not down_tradeable:
            reason = f"DOWN token not tradeable (ask={down_ask:.3f}, spread={spread_down:.3f}, cap={MAX_ENTRY_PRICE:.3f})"
        return _no_trade(reason, **dbg)

    kf = kelly_fraction(p, price)
    fraction = min(0.10, KELLY_SCALE * kf)
    budget = min(cash_amount * fraction, BET_SIZE_MAX)

    if budget < BET_SIZE_MIN:
        return _no_trade("Budget below minimum", budget=round(budget, 4), **dbg)

    size = math.floor(budget / price)
    if size < MIN_POSITION_SHARES:
        return _no_trade(
            f"Fewer than {MIN_POSITION_SHARES} shares",
            size=size,
            budget=round(budget, 4),
            price=price,
            **dbg,
        )

    spend = size * price
    if spend < 1.0:
        return _no_trade("Spend below $1 minimum", spend=round(spend, 4), size=size, price=price, **dbg)

    return Signal(
        action=action,
        price=round(price, 4),
        size=size,
        p_up=round(p_up, 4),
        edge=round(edge, 4),
        reason=f"fair={p:.3f}  mkt={price:.3f}  edge={edge:.4f}",
        debug=dbg,
    )
