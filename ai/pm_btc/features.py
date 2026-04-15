"""Feature extraction from a single logs-training.jsonl snapshot row.

The bot logs one snapshot per eval tick (~1s) while live. Each snapshot is a
fully-denormalized view of BTC state + PM books + timing. This module turns one
snapshot dict into a flat feature dict suitable for a DataFrame row.

Keep feature definitions here so dataset prep and live inference share the exact
same transform. If you add a feature, it goes in FEATURE_COLUMNS too.
"""
from __future__ import annotations

import math
from typing import Any, Optional

FEATURE_COLUMNS: list[str] = [
    "seconds_left",
    "time_frac",
    "btc_ret_30s",
    "btc_ret_60s",
    "btc_sigma_5m",
    "btc_distance_from_open",
    "up_ask",
    "up_bid",
    "up_spread",
    "up_ask_size_log",
    "up_bid_size_log",
    "down_ask",
    "down_bid",
    "down_spread",
    "down_ask_size_log",
    "down_bid_size_log",
    "book_imbalance_up",
    "book_imbalance_down",
    "implied_p_up_from_book",
    "pm_book_events_log",
    "feed_price_age",
    "feed_up_age",
    "feed_down_age",
]


def _safe_log1p(x: Optional[float]) -> float:
    if x is None or not math.isfinite(x) or x < 0:
        return 0.0
    return math.log1p(x)


def _imbalance(bid_sz: float, ask_sz: float) -> float:
    total = (bid_sz or 0.0) + (ask_sz or 0.0)
    if total <= 0:
        return 0.0
    return ((bid_sz or 0.0) - (ask_sz or 0.0)) / total


def extract_features(snapshot: dict[str, Any]) -> Optional[dict[str, float]]:
    """Extract a flat feature dict from one snapshot. Returns None if the row
    is unusable (books not live, BTC prices missing, etc)."""
    btc = snapshot.get("btc") or {}
    pm = snapshot.get("pm") or {}
    feeds = snapshot.get("feeds") or {}
    staleness = feeds.get("staleness") or {}

    bar_open = btc.get("bar_open") or 0.0
    current = btc.get("current_price") or 0.0
    if bar_open <= 0 or current <= 0:
        return None

    up_bid = pm.get("up_bid") or 0.0
    up_ask = pm.get("up_ask") or 0.0
    down_bid = pm.get("down_bid") or 0.0
    down_ask = pm.get("down_ask") or 0.0
    if not (0 < up_bid <= up_ask < 1 and 0 < down_bid <= down_ask < 1):
        return None

    seconds_left = snapshot.get("seconds_left") or 0
    # time_frac = 1.0 at bar open, 0.0 at bar end
    time_frac = max(0.0, min(1.0, seconds_left / 300.0))

    distance = math.log(current / bar_open) if bar_open > 0 else 0.0

    up_mid = 0.5 * (up_bid + up_ask)
    down_mid = 0.5 * (down_bid + down_ask)
    # Sum of UP mid and DOWN mid is usually near 1.0. Use UP share as a
    # noise-resistant implied prob — doesn't move if both tokens tighten.
    mid_sum = up_mid + down_mid
    implied_p_up = up_mid / mid_sum if mid_sum > 0 else 0.5

    return {
        "seconds_left": float(seconds_left),
        "time_frac": float(time_frac),
        "btc_ret_30s": float(btc.get("ret_30s") or 0.0),
        "btc_ret_60s": float(btc.get("ret_60s") or 0.0),
        "btc_sigma_5m": float(btc.get("sigma_5m") or 0.0),
        "btc_distance_from_open": float(distance),
        "up_ask": float(up_ask),
        "up_bid": float(up_bid),
        "up_spread": float(up_ask - up_bid),
        "up_ask_size_log": _safe_log1p(pm.get("up_ask_size")),
        "up_bid_size_log": _safe_log1p(pm.get("up_bid_size")),
        "down_ask": float(down_ask),
        "down_bid": float(down_bid),
        "down_spread": float(down_ask - down_bid),
        "down_ask_size_log": _safe_log1p(pm.get("down_ask_size")),
        "down_bid_size_log": _safe_log1p(pm.get("down_bid_size")),
        "book_imbalance_up": _imbalance(pm.get("up_bid_size") or 0.0, pm.get("up_ask_size") or 0.0),
        "book_imbalance_down": _imbalance(pm.get("down_bid_size") or 0.0, pm.get("down_ask_size") or 0.0),
        "implied_p_up_from_book": float(implied_p_up),
        "pm_book_events_log": _safe_log1p(pm.get("book_events")),
        "feed_price_age": float(staleness.get("price_age") or 0.0),
        "feed_up_age": float(staleness.get("pm_up_age") or 0.0),
        "feed_down_age": float(staleness.get("pm_down_age") or 0.0),
    }
