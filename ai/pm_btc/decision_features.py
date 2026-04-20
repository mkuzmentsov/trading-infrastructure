"""Feature extraction for PM BTC decision models.

These models are different from the existing `train.py` entry-direction model:
- entry gate: should we bid on the currently proposed trade?
- exit gate: should we exit the current position now?

Both operate on the same raw `logs-training.jsonl` snapshots the bot writes.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from features import FEATURE_COLUMNS as BASE_FEATURE_COLUMNS
from features import extract_features as extract_base_features


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _safe_log1p(value: Any) -> float:
    value_f = _safe_float(value)
    if value_f < 0:
        return 0.0
    return math.log1p(value_f)


def _current_side_values(snapshot: dict[str, Any], direction: str) -> dict[str, float]:
    pm = snapshot.get("pm") or {}
    up_bid_size = _safe_float(pm.get("up_bid_size"))
    up_ask_size = _safe_float(pm.get("up_ask_size"))
    down_bid_size = _safe_float(pm.get("down_bid_size"))
    down_ask_size = _safe_float(pm.get("down_ask_size"))
    up_total = up_bid_size + up_ask_size
    down_total = down_bid_size + down_ask_size
    if direction == "UP":
        return {
            "bid": _safe_float(pm.get("up_bid")),
            "ask": _safe_float(pm.get("up_ask")),
            "spread": _safe_float(pm.get("up_ask")) - _safe_float(pm.get("up_bid")),
            "bid_size_log": _safe_log1p(pm.get("up_bid_size")),
            "ask_size_log": _safe_log1p(pm.get("up_ask_size")),
            "book_imbalance": ((up_bid_size - up_ask_size) / up_total) if up_total > 0 else 0.0,
        }
    return {
        "bid": _safe_float(pm.get("down_bid")),
        "ask": _safe_float(pm.get("down_ask")),
        "spread": _safe_float(pm.get("down_ask")) - _safe_float(pm.get("down_bid")),
        "bid_size_log": _safe_log1p(pm.get("down_bid_size")),
        "ask_size_log": _safe_log1p(pm.get("down_ask_size")),
        "book_imbalance": ((down_bid_size - down_ask_size) / down_total) if down_total > 0 else 0.0,
    }


ENTRY_EXTRA_COLUMNS: list[str] = [
    "direction_up",
    "candidate_price",
    "candidate_bid",
    "candidate_spread",
    "candidate_mark_to_market",
    "candidate_ask_size_log",
    "candidate_bid_size_log",
    "signal_p_up",
    "signal_edge",
    "signal_side_edge",
    "signal_opposite_edge",
    "signal_edge_gap",
    "signal_size",
    "book_divergence",
    "price_source_binance",
    "binance_distance_from_open",
    "binance_chainlink_divergence",
    "binance_age",
]

EXIT_EXTRA_COLUMNS: list[str] = [
    "position_direction_up",
    "entry_price",
    "entry_edge",
    "entry_p_up",
    "entry_seconds_left",
    "time_in_position",
    "current_side_bid",
    "current_side_ask",
    "current_side_spread",
    "current_mark_to_market",
    "current_unrealized",
    "peak_bid",
    "peak_unrealized",
    "drawdown_from_peak",
    "signed_btc_distance",
    "signal_p_up",
    "signal_edge",
    "signal_side_edge",
    "signal_opposite_edge",
    "signal_edge_gap",
    "current_side_bid_size_log",
    "current_side_ask_size_log",
    "current_side_book_imbalance",
    "price_source_binance",
    "binance_distance_from_open",
    "binance_chainlink_divergence",
    "binance_age",
]

ENTRY_FEATURE_COLUMNS: list[str] = BASE_FEATURE_COLUMNS + ENTRY_EXTRA_COLUMNS
EXIT_FEATURE_COLUMNS: list[str] = BASE_FEATURE_COLUMNS + EXIT_EXTRA_COLUMNS


def extract_entry_features(snapshot: dict[str, Any]) -> Optional[dict[str, float]]:
    base = extract_base_features(snapshot)
    if base is None:
        return None

    signal = snapshot.get("signal") or {}
    action = signal.get("action")
    if action not in {"BUY_UP", "BUY_DOWN"}:
        return None

    direction = "UP" if action == "BUY_UP" else "DOWN"
    pm = snapshot.get("pm") or {}
    btc = snapshot.get("btc") or {}
    debug = signal.get("debug") or {}
    side = _current_side_values(snapshot, direction)

    signal_p_up = _safe_float(signal.get("p_up"), 0.5)
    signal_edge = _safe_float(signal.get("edge"))
    side_edge = _safe_float(debug.get("net_up" if direction == "UP" else "net_down"), signal_edge)
    opposite_edge = _safe_float(debug.get("net_down" if direction == "UP" else "net_up"))

    bar_open = _safe_float(btc.get("bar_open"))
    chainlink_price = _safe_float(btc.get("current_price"))
    binance_price = _safe_float(btc.get("binance_price"))
    best_price = binance_price if binance_price > 0 else chainlink_price

    features = dict(base)
    features.update(
        {
            "direction_up": 1.0 if direction == "UP" else 0.0,
            "candidate_price": _safe_float(signal.get("price"), side["ask"]),
            "candidate_bid": side["bid"],
            "candidate_spread": side["spread"],
            "candidate_mark_to_market": side["bid"] - _safe_float(signal.get("price"), side["ask"]),
            "candidate_ask_size_log": side["ask_size_log"],
            "candidate_bid_size_log": side["bid_size_log"],
            "signal_p_up": signal_p_up,
            "signal_edge": signal_edge,
            "signal_side_edge": side_edge,
            "signal_opposite_edge": opposite_edge,
            "signal_edge_gap": side_edge - opposite_edge,
            "signal_size": _safe_float(signal.get("size")),
            "book_divergence": _safe_float(debug.get("book_divergence")),
            "price_source_binance": 1.0 if debug.get("price_source") == "binance" else 0.0,
            "binance_distance_from_open": math.log(best_price / bar_open) if bar_open > 0 and best_price > 0 else 0.0,
            "binance_chainlink_divergence": math.log(best_price / chainlink_price) if best_price > 0 and chainlink_price > 0 else 0.0,
            "binance_age": _safe_float(btc.get("binance_age")),
        }
    )
    return features


def extract_exit_features(snapshot: dict[str, Any]) -> Optional[dict[str, float]]:
    base = extract_base_features(snapshot)
    if base is None:
        return None

    position = snapshot.get("position") or {}
    direction = position.get("direction")
    if direction not in {"UP", "DOWN"}:
        return None

    signal = snapshot.get("signal") or {}
    debug = signal.get("debug") or {}
    btc = snapshot.get("btc") or {}
    side = _current_side_values(snapshot, direction)

    entry_price = _safe_float(position.get("entry_price"))
    peak_bid = _safe_float(position.get("peak_bid"), entry_price)
    current_bid = side["bid"]
    unrealized = current_bid - entry_price
    peak_unrealized = peak_bid - entry_price
    seconds_left = _safe_float(snapshot.get("seconds_left"))
    entry_seconds_left = _safe_float(position.get("entry_seconds_left"), seconds_left)
    signal_p_up = _safe_float(signal.get("p_up"), 0.5)

    bar_open = _safe_float(btc.get("bar_open"))
    chainlink_price = _safe_float(btc.get("current_price"))
    binance_price = _safe_float(btc.get("binance_price"))
    best_price = binance_price if binance_price > 0 else chainlink_price
    btc_distance = math.log(best_price / bar_open) if bar_open > 0 and best_price > 0 else 0.0
    signed_btc_distance = btc_distance if direction == "UP" else -btc_distance

    side_edge = _safe_float(debug.get("net_up" if direction == "UP" else "net_down"))
    opposite_edge = _safe_float(debug.get("net_down" if direction == "UP" else "net_up"))

    features = dict(base)
    features.update(
        {
            "position_direction_up": 1.0 if direction == "UP" else 0.0,
            "entry_price": entry_price,
            "entry_edge": _safe_float(position.get("entry_edge")),
            "entry_p_up": _safe_float(position.get("entry_p_up"), 0.5),
            "entry_seconds_left": entry_seconds_left,
            "time_in_position": max(0.0, entry_seconds_left - seconds_left),
            "current_side_bid": current_bid,
            "current_side_ask": side["ask"],
            "current_side_spread": side["spread"],
            "current_mark_to_market": current_bid - entry_price,
            "current_unrealized": unrealized,
            "peak_bid": peak_bid,
            "peak_unrealized": peak_unrealized,
            "drawdown_from_peak": peak_bid - current_bid,
            "signed_btc_distance": signed_btc_distance,
            "signal_p_up": signal_p_up,
            "signal_edge": _safe_float(signal.get("edge")),
            "signal_side_edge": side_edge,
            "signal_opposite_edge": opposite_edge,
            "signal_edge_gap": side_edge - opposite_edge,
            "current_side_bid_size_log": side["bid_size_log"],
            "current_side_ask_size_log": side["ask_size_log"],
            "current_side_book_imbalance": side["book_imbalance"],
            "price_source_binance": 1.0 if debug.get("price_source") == "binance" else 0.0,
            "binance_distance_from_open": btc_distance,
            "binance_chainlink_divergence": math.log(best_price / chainlink_price) if best_price > 0 and chainlink_price > 0 else 0.0,
            "binance_age": _safe_float(btc.get("binance_age")),
        }
    )
    return features
