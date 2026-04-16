"""
Latency arbitrage signal for BTC 5-minute binary markets.

Core idea: Binance BTC/USDT trades propagate 1-3 seconds before the
Chainlink oracle that Polymarket prices off. When BTC has already moved
on Binance but the PM book is still priced on the stale oracle, we buy
the cheap side and hold to expiry.

Three filters separate real mispricing from noise:
1. Minimum BTC distance — don't bet on tiny moves near the bar open.
2. Book divergence — only enter when our model disagrees with the book's
   implied probability. If the book already reflects the BTC move, there's
   no mispricing to capture.
3. Adaptive timing — later in the bar, the outcome is more certain and
   smaller edges are profitable.

All positions are held to expiry — the edge comes from information
advantage at entry, not from timing the exit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from config import (
    BET_SIZE_MAX,
    BET_SIZE_MIN,
    ENTRY_MIN_SECONDS_LEFT,
    KELLY_SCALE,
    MAX_BUDGET_FRACTION,
    MAX_ENTRY_PRICE,
    MAX_ENTRY_SPREAD,
    MIN_EDGE,
    MIN_ENTRY_PRICE,
    MIN_POSITION_SHARES,
    MODEL_PROB_CEIL,
    MODEL_PROB_FLOOR,
    TAKER_FEE_BPS,
)

# ── Smart entry thresholds ───────────────────────────────────────────────────
# Minimum absolute log-distance from bar_open before we consider an entry.
# Tiny moves near the open produce ~50/50 outcomes — no real edge.
MIN_BTC_DISTANCE = float(__import__("os").getenv("MIN_BTC_DISTANCE", "0.0004"))

# Minimum divergence between our model's fair P(UP) and what the book implies.
# If the book already reflects the BTC move, there's no mispricing to capture.
MIN_BOOK_DIVERGENCE = float(__import__("os").getenv("MIN_BOOK_DIVERGENCE", "0.04"))

# Late-bar bonus: reduce MIN_EDGE when fewer seconds remain, because the
# outcome is more certain.  edge_threshold = MIN_EDGE * (1 - bonus)
# when seconds_left < LATE_ENTRY_SECS.
LATE_ENTRY_SECS = int(__import__("os").getenv("LATE_ENTRY_SECS", "90"))
LATE_ENTRY_EDGE_DISCOUNT = float(__import__("os").getenv("LATE_ENTRY_EDGE_DISCOUNT", "0.30"))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class Signal:
    action: str
    price: Optional[float]
    size: int
    p_up: float
    edge: float
    reason: str
    debug: dict = field(default_factory=dict)


def _fair_p_up(
    bar_open: float,
    best_price: float,
    sigma_5m: float,
    seconds_left: int,
) -> float:
    """Compute P(bar resolves UP) using the freshest available BTC price.

    Uses a simple normal model of remaining log-returns. No drift —
    drift estimation was hurting accuracy in backtests. The distance
    from open is the main driver; sigma_rem controls how decisive
    the current distance is.
    """
    if bar_open <= 0 or best_price <= 0:
        return 0.5

    distance = math.log(best_price / bar_open)
    time_frac = max(seconds_left / 300.0, 1e-6)
    sigma_rem = max(sigma_5m * math.sqrt(time_frac), 1e-6)

    z = distance / sigma_rem
    # Light clamp to avoid extreme probabilities on huge moves
    z = _clip(z, -3.0, 3.0)
    raw_p = _norm_cdf(z)

    # Minimal shrinkage — we trust the price signal, especially with
    # Binance data. Only pull extremes slightly toward 0.5.
    shrink = 0.92
    p = 0.5 + shrink * (raw_p - 0.5)
    return _clip(p, MODEL_PROB_FLOOR, MODEL_PROB_CEIL)


def _book_implied_p_up(
    up_bid: float, up_ask: float, down_bid: float, down_ask: float
) -> float:
    """What the PM book currently implies about P(UP)."""
    up_mid = 0.5 * (up_bid + up_ask)
    down_mid = 0.5 * (down_bid + down_ask)
    total = up_mid + down_mid
    if total <= 0:
        return 0.5
    return up_mid / total


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
    model_p_up: Optional[float] = None,
    require_budget: bool = True,
    binance_price: float = 0.0,
) -> Signal:
    def _no_trade(reason: str, p_up_value: float = 0.5, edge_value: float = 0.0, **kw) -> Signal:
        return Signal(
            action="NO_TRADE",
            price=None,
            size=0,
            p_up=round(p_up_value, 4),
            edge=round(edge_value, 4),
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

    # Use Binance price if available and fresh (< 5s old),
    # otherwise fall back to Chainlink.
    best_price = current_price
    price_source = "chainlink"
    if binance_price > 0:
        best_price = binance_price
        price_source = "binance"

    # BTC distance from bar open — the primary signal
    btc_distance = math.log(best_price / bar_open) if bar_open > 0 and best_price > 0 else 0.0

    # Our fair probability using the freshest price
    p_up = _fair_p_up(bar_open, best_price, sigma_5m, seconds_left)
    p_down = 1.0 - p_up

    # What the book currently thinks
    implied = _book_implied_p_up(up_bid, up_ask, down_bid, down_ask)

    # How much our model disagrees with the book — this is the real signal.
    # If we think P(UP)=0.75 but the book says 0.55, there's a 0.20 mispricing.
    book_divergence = abs(p_up - implied)

    # Distances for diagnostics
    chainlink_distance = math.log(current_price / bar_open) if bar_open > 0 else 0.0
    binance_distance = math.log(binance_price / bar_open) if binance_price > 0 and bar_open > 0 else 0.0
    price_divergence = binance_distance - chainlink_distance if binance_price > 0 else 0.0

    # Edge: fair probability minus the ask price we'd pay, minus taker fee.
    # With hold-to-expiry, there's no exit cost — payout is 1.00 or 0.00.
    fee = TAKER_FEE_BPS / 10000.0
    net_up = p_up - up_ask - fee
    net_down = p_down - down_ask - fee

    # Adaptive edge threshold: later in the bar, outcomes are more certain,
    # so a smaller edge is still profitable.
    edge_threshold = MIN_EDGE
    if seconds_left < LATE_ENTRY_SECS:
        time_ratio = seconds_left / max(LATE_ENTRY_SECS, 1)
        discount = LATE_ENTRY_EDGE_DISCOUNT * (1.0 - time_ratio)
        edge_threshold = MIN_EDGE * (1.0 - discount)

    dbg = dict(
        p_up=round(p_up, 4),
        p_down=round(p_down, 4),
        net_up=round(net_up, 4),
        net_down=round(net_down, 4),
        sigma_5m=round(sigma_5m, 6),
        seconds_left=seconds_left,
        price_source=price_source,
        best_price=round(best_price, 2),
        chainlink_price=round(current_price, 2),
        binance_price=round(binance_price, 2) if binance_price > 0 else None,
        btc_distance=round(btc_distance, 6),
        chainlink_distance=round(chainlink_distance, 6),
        binance_distance=round(binance_distance, 6) if binance_price > 0 else None,
        price_divergence=round(price_divergence, 6) if binance_price > 0 else None,
        book_implied_p_up=round(implied, 4),
        book_divergence=round(book_divergence, 4),
        edge_threshold=round(edge_threshold, 4),
        spread_up=round(spread_up, 4),
        spread_down=round(spread_down, 4),
        fee=round(fee, 4),
        p_up_model=round(float(model_p_up), 4) if model_p_up is not None else None,
    )

    # ── Smart filters ────────────────────────────────────────────────────────
    # Filter 1: BTC must have moved meaningfully from the bar open.
    # Tiny moves produce ~50/50 outcomes where "edge" is just noise.
    if abs(btc_distance) < MIN_BTC_DISTANCE:
        return _no_trade(
            f"BTC too close to open (dist={btc_distance:+.5f}, min={MIN_BTC_DISTANCE:.5f})",
            p_up_value=p_up, edge_value=max(net_up, net_down), **dbg,
        )

    # Filter 2: Our model must meaningfully disagree with the book.
    # If the book already reflects the BTC move, there's no mispricing.
    if book_divergence < MIN_BOOK_DIVERGENCE:
        return _no_trade(
            f"Book already priced in (model_div={book_divergence:.4f}, min={MIN_BOOK_DIVERGENCE:.4f})",
            p_up_value=p_up, edge_value=max(net_up, net_down), **dbg,
        )

    # Tradeability filters
    up_tradeable = MIN_ENTRY_PRICE <= up_ask <= MAX_ENTRY_PRICE and spread_up <= MAX_ENTRY_SPREAD
    down_tradeable = MIN_ENTRY_PRICE <= down_ask <= MAX_ENTRY_PRICE and spread_down <= MAX_ENTRY_SPREAD

    # Pick the side with the most edge (using adaptive threshold)
    if net_up >= net_down and net_up >= edge_threshold and up_tradeable:
        action, price, p, edge = "BUY_UP", up_ask, p_up, net_up
    elif net_down > net_up and net_down >= edge_threshold and down_tradeable:
        action, price, p, edge = "BUY_DOWN", down_ask, p_down, net_down
    else:
        reason = f"No edge above threshold ({edge_threshold:.4f})"
        if net_up >= edge_threshold and not up_tradeable:
            reason = f"UP not tradeable (ask={up_ask:.3f}, spread={spread_up:.3f})"
        elif net_down >= edge_threshold and not down_tradeable:
            reason = f"DOWN not tradeable (ask={down_ask:.3f}, spread={spread_down:.3f})"
        return _no_trade(reason, p_up_value=p_up, edge_value=max(net_up, net_down), **dbg)

    if not require_budget:
        return Signal(
            action=action,
            price=round(price, 4),
            size=0,
            p_up=round(p_up, 4),
            edge=round(edge, 4),
            reason=f"fair={p:.3f} mkt={price:.3f} edge={edge:.4f} book_div={book_divergence:.3f} src={price_source}",
            debug=dbg,
        )

    budget = min(cash_amount * MAX_BUDGET_FRACTION, BET_SIZE_MAX)
    if budget < BET_SIZE_MIN:
        return _no_trade("Budget below minimum", p_up_value=p_up, edge_value=edge, budget=round(budget, 4), **dbg)

    size = math.floor(budget / price)
    if size < MIN_POSITION_SHARES:
        return _no_trade(
            f"Fewer than {MIN_POSITION_SHARES} shares",
            p_up_value=p_up, edge_value=edge, size=size, **dbg,
        )

    return Signal(
        action=action,
        price=round(price, 4),
        size=size,
        p_up=round(p_up, 4),
        edge=round(edge, 4),
        reason=f"fair={p:.3f} mkt={price:.3f} edge={edge:.4f} book_div={book_divergence:.3f} src={price_source}",
        debug=dbg,
    )
