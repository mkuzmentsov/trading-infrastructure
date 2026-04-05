"""
Mathematical signal generation — no AI/ML.

Models the remaining BTC move as a normal log-return:

  log(S_T) ~ Normal(log(S) + μ_rem, σ_rem²)

So:

  p_up = Φ( (log(S) + μ_rem - log(O)) / σ_rem )

Where:
  O      = bar open price
  S      = current price
  μ_rem  = expected drift for remaining time (from microstructure)
  σ_rem  = expected vol for remaining time (scaled from recent realized vol)
  Φ      = standard normal CDF

Edge = fair_probability - market_ask - cost_buffer
Size = half-Kelly, capped at [BET_SIZE_MIN, BET_SIZE_MAX]
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from config import (
    BET_SIZE_MAX, BET_SIZE_MIN, COST_BUFFER,
    DRIFT_A1, DRIFT_A2, DRIFT_A3, DRIFT_A4,
    KELLY_SCALE, MIN_EDGE,
)


# ── Math primitives ───────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


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
    """
    Scaled projection of 5-minute drift based on microstructure signals.
    Coefficients are hand-tuned placeholders — improve via backtesting.
    """
    time_frac = seconds_left / 300.0
    raw = (
        DRIFT_A1 * ret_30s +
        DRIFT_A2 * ret_60s +
        DRIFT_A3 * imbalance +
        DRIFT_A4 * distance_from_open
    )
    return time_frac * raw


def estimate_remaining_sigma(seconds_left: int, sigma_5m: float) -> float:
    """Scale full-bar volatility to remaining time (sqrt-of-time rule)."""
    time_frac = max(seconds_left / 300.0, 1e-6)
    return max(sigma_5m * math.sqrt(time_frac), 1e-6)


def fair_probability_up(
    open_price: float,
    current_price: float,
    mu_rem: float,
    sigma_rem: float,
) -> float:
    """P(S_T > O) under lognormal model.

    Z-score is capped at ±1.5 (~93% max confidence) to prevent the model
    from becoming overconfident due to noisy microstructure signals.
    """
    if open_price <= 0 or current_price <= 0:
        return 0.5
    z = (math.log(current_price) + mu_rem - math.log(open_price)) / sigma_rem
    z = max(-1.5, min(1.5, z))          # cap: p range [0.067, 0.933]
    return max(0.05, min(0.95, _norm_cdf(z)))


def kelly_fraction(p: float, c: float) -> float:
    """Full Kelly fraction for a YES contract bought at price c."""
    if c >= 1.0:
        return 0.0
    return max(0.0, (p - c) / (1.0 - c))


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class Signal:
    action: str                   # BUY_UP / BUY_DOWN / NO_TRADE
    price: Optional[float]
    size: int                     # number of shares
    p_up: float
    edge: float
    reason: str
    debug: dict = field(default_factory=dict)


# ── Main entry point ──────────────────────────────────────────────────────────

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
    up_ask: float,
    down_ask: float,
) -> Signal:
    """
    Compute a trading signal from current BTC and Polymarket state.

    Returns a Signal with action=NO_TRADE if no positive edge is found.
    """
    def _no_trade(reason: str, **kw) -> Signal:
        return Signal(action="NO_TRADE", price=None, size=0,
                      p_up=0.5, edge=0.0, reason=reason, debug=kw)

    if seconds_left < 10:
        return _no_trade("Too little time left")

    if bar_open <= 0 or current_price <= 0:
        return _no_trade("Missing BTC prices")

    imbalance = book_imbalance(bid_vol_top, ask_vol_top)
    distance  = math.log(current_price / bar_open)

    mu_rem    = estimate_remaining_drift(seconds_left, ret_30s, ret_60s, distance, imbalance)
    sigma_rem = estimate_remaining_sigma(seconds_left, sigma_5m)
    p_up      = fair_probability_up(bar_open, current_price, mu_rem, sigma_rem)
    p_down    = 1.0 - p_up

    net_up   = p_up   - up_ask   - COST_BUFFER
    net_down = p_down - down_ask - COST_BUFFER

    dbg = dict(
        p_up=round(p_up, 4),       p_down=round(p_down, 4),
        net_up=round(net_up, 4),   net_down=round(net_down, 4),
        mu_rem=round(mu_rem, 6),   sigma_rem=round(sigma_rem, 6),
        imbalance=round(imbalance, 4), distance=round(distance, 6),
        seconds_left=seconds_left,
    )

    # Reject near-resolved markets — model edge is meaningless when token < 5¢ or > 95¢
    up_tradeable   = 0.05 <= up_ask   <= 0.95
    down_tradeable = 0.05 <= down_ask <= 0.95

    if net_up >= net_down and net_up >= MIN_EDGE and up_tradeable:
        action, price, p, edge = "BUY_UP",   up_ask,   p_up,   net_up
    elif net_down > net_up and net_down >= MIN_EDGE and down_tradeable:
        action, price, p, edge = "BUY_DOWN", down_ask, p_down, net_down
    else:
        reason = "No edge above threshold"
        if net_up >= MIN_EDGE and not up_tradeable:
            reason = f"UP token out of range (ask={up_ask:.3f})"
        elif net_down >= MIN_EDGE and not down_tradeable:
            reason = f"DOWN token out of range (ask={down_ask:.3f})"
        return _no_trade(reason, **dbg)

    kf       = kelly_fraction(p, price)
    fraction = min(0.10, KELLY_SCALE * kf)
    budget   = min(cash_amount * fraction, BET_SIZE_MAX)

    if budget < BET_SIZE_MIN:
        return _no_trade("Budget below minimum", budget=round(budget, 4), **dbg)

    size = math.floor(budget / price)
    if size < 5:
        return _no_trade("Fewer than 5 shares", size=size, budget=round(budget, 4), price=price)

    spend = size * price
    if spend < 1.0:
        return _no_trade("Spend below $1 minimum", spend=round(spend, 4), size=size, price=price)

    return Signal(
        action=action,
        price=round(price, 4),
        size=size,
        p_up=round(p_up, 4),
        edge=round(edge, 4),
        reason=f"fair={p:.3f}  mkt={price:.3f}  edge={edge:.4f}",
        debug=dbg,
    )
