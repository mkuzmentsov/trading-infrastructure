"""v2 feature extraction for the PM BTC entry gate.

Differences from decision_features.py:
  * Rate-of-change features computed from a sorted window of prior snapshots
    in the same bar (bid velocity, book-event rate, divergence delta).
  * btc_accel = ret_30s - ret_60s (signed BTC momentum acceleration).
  * Closed-form fair P(UP) from math_signal._fair_p_up bundled as a feature
    (so the tree can use it AND we can blend at inference).
  * Monotonic direction map used by the trainer for LightGBM constraints.

The extractor signature takes an (in-bar, sorted-ascending) list of snapshots
so callers can reuse history across rows without re-scanning.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Optional

from features import FEATURE_COLUMNS as BASE_FEATURE_COLUMNS
from features import extract_features as extract_base_features

# Pull in the live bot's closed-form prior so the feature and live inference
# share the exact same formula. The live scripts dir must be on sys.path.
_SCRIPTS_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "polymarket",
        "k8s",
        "helm",
        "polymarket-btc-bot",
        "files",
        "scripts",
    )
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from math_signal import _fair_p_up as _closed_form_p_up  # type: ignore
except Exception:
    def _closed_form_p_up(bar_open: float, best_price: float, sigma_5m: float, seconds_left: int) -> float:
        # Inline fallback — same formula as math_signal._fair_p_up without the clips.
        if bar_open <= 0 or best_price <= 0:
            return 0.5
        distance = math.log(best_price / bar_open)
        time_frac = max(seconds_left / 300.0, 1e-6)
        sigma_rem = max(sigma_5m * math.sqrt(time_frac), 1e-6)
        z = max(-3.0, min(3.0, distance / sigma_rem))
        raw_p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        return 0.5 + 0.92 * (raw_p - 0.5)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _safe_log1p(value: Any) -> float:
    v = _safe_float(value)
    return math.log1p(v) if v >= 0 else 0.0


def _side_values(snapshot: dict[str, Any], direction: str) -> dict[str, float]:
    pm = snapshot.get("pm") or {}
    if direction == "UP":
        bid = _safe_float(pm.get("up_bid"))
        ask = _safe_float(pm.get("up_ask"))
        bid_sz = _safe_float(pm.get("up_bid_size"))
        ask_sz = _safe_float(pm.get("up_ask_size"))
    else:
        bid = _safe_float(pm.get("down_bid"))
        ask = _safe_float(pm.get("down_ask"))
        bid_sz = _safe_float(pm.get("down_bid_size"))
        ask_sz = _safe_float(pm.get("down_ask_size"))
    total = bid_sz + ask_sz
    return {
        "bid": bid,
        "ask": ask,
        "spread": ask - bid,
        "bid_size": bid_sz,
        "ask_size": ask_sz,
        "book_imbalance": ((bid_sz - ask_sz) / total) if total > 0 else 0.0,
    }


def _lookback_snap(
    prior_rows: list[dict[str, Any]],
    now_ts: float,
    target_lookback_secs: float,
) -> Optional[dict[str, Any]]:
    """Return the prior snapshot closest to (now_ts - target_lookback)."""
    if not prior_rows:
        return None
    target = now_ts - target_lookback_secs
    best = None
    best_gap = float("inf")
    for row in prior_rows:
        rts = _safe_float(row.get("ts"))
        if rts <= 0 or rts > now_ts:
            continue
        gap = abs(rts - target)
        if gap < best_gap:
            best_gap = gap
            best = row
    return best


def _pm_bid(row: dict[str, Any], direction: str) -> float:
    pm = row.get("pm") or {}
    key = "up_bid" if direction == "UP" else "down_bid"
    return _safe_float(pm.get(key))


def _book_events(row: dict[str, Any]) -> float:
    pm = row.get("pm") or {}
    return _safe_float(pm.get("book_events"))


def _best_btc(row: dict[str, Any]) -> float:
    btc = row.get("btc") or {}
    binance = _safe_float(btc.get("binance_price"))
    if binance > 0:
        return binance
    return _safe_float(btc.get("current_price"))


def _divergence(row: dict[str, Any]) -> float:
    btc = row.get("btc") or {}
    bar_open = _safe_float(btc.get("bar_open"))
    best = _best_btc(row)
    chainlink = _safe_float(btc.get("current_price"))
    if bar_open <= 0 or best <= 0 or chainlink <= 0:
        return 0.0
    return math.log(best / chainlink)


def _velocity(
    current_value: float,
    current_ts: float,
    prior_row: Optional[dict[str, Any]],
    accessor,
) -> float:
    if prior_row is None:
        return 0.0
    prior_ts = _safe_float(prior_row.get("ts"))
    if prior_ts <= 0 or current_ts <= prior_ts:
        return 0.0
    prior_value = accessor(prior_row)
    dt = current_ts - prior_ts
    return (current_value - prior_value) / max(dt, 1.0)


ENTRY_EXTRA_COLUMNS_V2: list[str] = [
    # v1 carry-overs that remain useful
    "direction_up",
    "candidate_price",
    "candidate_bid",
    "candidate_spread",
    "candidate_ask_size_log",
    "candidate_bid_size_log",
    "candidate_book_imbalance",
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
    # v2 additions — rate-of-change / microstructure dynamics
    "up_bid_velocity_5s",
    "up_bid_velocity_15s",
    "down_bid_velocity_5s",
    "down_bid_velocity_15s",
    "candidate_bid_velocity_15s",
    "book_events_rate_15s",
    "btc_ret_15s",
    "btc_accel",
    "divergence_delta_15s",
    # closed-form prior, exposed as a feature so the tree sees it explicitly
    "closed_form_p_up",
    "closed_form_side_prob",
]

ENTRY_FEATURE_COLUMNS_V2: list[str] = BASE_FEATURE_COLUMNS + ENTRY_EXTRA_COLUMNS_V2


# Monotone constraint signs: +1 monotone increasing, -1 decreasing, 0 free.
# Intentionally sparse — only impose constraints we're confident about
# directionally. Over-constraining with tiny data hurts more than helps.
ENTRY_MONOTONE_CONSTRAINTS: dict[str, int] = {
    "signal_side_edge": +1,          # more side edge → higher entry probability
    "signal_edge": +1,
    "signal_edge_gap": +1,            # edge on side minus opposite
    "signal_opposite_edge": -1,       # opposite side also has edge → worse
    "feed_price_age": -1,             # stale feeds → worse
    "feed_up_age": -1,
    "feed_down_age": -1,
    "binance_age": -1,
    "candidate_spread": -1,           # wider spread → worse
    "candidate_bid_size_log": +1,     # thicker exit bid → better
    "closed_form_p_up": +1,           # prior directly informs outcome prob
    "closed_form_side_prob": +1,      # prior for the chosen side
    "book_divergence": +1,            # bigger model/book gap → more alpha
    "signal_size": +1,                # higher-confidence signal → higher score
}


def extract_entry_features_v2(
    snapshot: dict[str, Any],
    prior_rows: list[dict[str, Any]],
) -> Optional[dict[str, float]]:
    """Extract v2 entry features. prior_rows are in-bar snapshots with ts<=snap.ts,
    sorted ascending. They supply rate-of-change context."""
    base = extract_base_features(snapshot)
    if base is None:
        return None

    signal = snapshot.get("signal") or {}
    action = signal.get("action")
    if action not in {"BUY_UP", "BUY_DOWN"}:
        return None

    direction = "UP" if action == "BUY_UP" else "DOWN"
    btc = snapshot.get("btc") or {}
    debug = signal.get("debug") or {}
    side = _side_values(snapshot, direction)

    signal_p_up = _safe_float(signal.get("p_up"), 0.5)
    signal_edge = _safe_float(signal.get("edge"))
    side_edge = _safe_float(debug.get("net_up" if direction == "UP" else "net_down"), signal_edge)
    opposite_edge = _safe_float(debug.get("net_down" if direction == "UP" else "net_up"))

    bar_open = _safe_float(btc.get("bar_open"))
    chainlink = _safe_float(btc.get("current_price"))
    binance = _safe_float(btc.get("binance_price"))
    best_price = binance if binance > 0 else chainlink

    now_ts = _safe_float(snapshot.get("ts"))
    prior_5s = _lookback_snap(prior_rows, now_ts, 5.0)
    prior_15s = _lookback_snap(prior_rows, now_ts, 15.0)
    prior_30s = _lookback_snap(prior_rows, now_ts, 30.0)

    current_up_bid = _pm_bid(snapshot, "UP")
    current_down_bid = _pm_bid(snapshot, "DOWN")
    up_vel_5s = _velocity(current_up_bid, now_ts, prior_5s, lambda r: _pm_bid(r, "UP"))
    up_vel_15s = _velocity(current_up_bid, now_ts, prior_15s, lambda r: _pm_bid(r, "UP"))
    down_vel_5s = _velocity(current_down_bid, now_ts, prior_5s, lambda r: _pm_bid(r, "DOWN"))
    down_vel_15s = _velocity(current_down_bid, now_ts, prior_15s, lambda r: _pm_bid(r, "DOWN"))
    candidate_vel_15s = up_vel_15s if direction == "UP" else down_vel_15s

    current_events = _book_events(snapshot)
    events_rate_15s = _velocity(current_events, now_ts, prior_15s, _book_events)

    current_best_btc = best_price
    prior_best_btc = _best_btc(prior_15s) if prior_15s else 0.0
    btc_ret_15s = math.log(current_best_btc / prior_best_btc) if (current_best_btc > 0 and prior_best_btc > 0) else 0.0

    ret_30s = _safe_float(btc.get("ret_30s"))
    ret_60s = _safe_float(btc.get("ret_60s"))
    btc_accel = ret_30s - ret_60s

    current_div = _divergence(snapshot)
    prior_div = _divergence(prior_15s) if prior_15s else 0.0
    divergence_delta_15s = current_div - prior_div

    seconds_left = int(_safe_float(snapshot.get("seconds_left")))
    sigma_5m = _safe_float(btc.get("sigma_5m"))
    closed_form_p_up = float(_closed_form_p_up(bar_open, best_price, sigma_5m, seconds_left))
    closed_form_side_prob = closed_form_p_up if direction == "UP" else (1.0 - closed_form_p_up)

    candidate_bid_size_log = math.log1p(side["bid_size"]) if side["bid_size"] >= 0 else 0.0
    candidate_ask_size_log = math.log1p(side["ask_size"]) if side["ask_size"] >= 0 else 0.0

    features = dict(base)
    features.update(
        {
            "direction_up": 1.0 if direction == "UP" else 0.0,
            "candidate_price": _safe_float(signal.get("price"), side["ask"]),
            "candidate_bid": side["bid"],
            "candidate_spread": side["spread"],
            "candidate_ask_size_log": candidate_ask_size_log,
            "candidate_bid_size_log": candidate_bid_size_log,
            "candidate_book_imbalance": side["book_imbalance"],
            "signal_p_up": signal_p_up,
            "signal_edge": signal_edge,
            "signal_side_edge": side_edge,
            "signal_opposite_edge": opposite_edge,
            "signal_edge_gap": side_edge - opposite_edge,
            "signal_size": _safe_float(signal.get("size")),
            "book_divergence": _safe_float(debug.get("book_divergence")),
            "price_source_binance": 1.0 if debug.get("price_source") == "binance" else 0.0,
            "binance_distance_from_open": math.log(best_price / bar_open) if (bar_open > 0 and best_price > 0) else 0.0,
            "binance_chainlink_divergence": current_div,
            "binance_age": _safe_float(btc.get("binance_age")),
            "up_bid_velocity_5s": up_vel_5s,
            "up_bid_velocity_15s": up_vel_15s,
            "down_bid_velocity_5s": down_vel_5s,
            "down_bid_velocity_15s": down_vel_15s,
            "candidate_bid_velocity_15s": candidate_vel_15s,
            "book_events_rate_15s": events_rate_15s,
            "btc_ret_15s": btc_ret_15s,
            "btc_accel": btc_accel,
            "divergence_delta_15s": divergence_delta_15s,
            "closed_form_p_up": closed_form_p_up,
            "closed_form_side_prob": closed_form_side_prob,
        }
    )
    features["_direction"] = direction
    features["_candidate_price"] = float(features["candidate_price"])
    features["_candidate_bid_size"] = float(side["bid_size"])
    return features


def monotone_constraints_for(columns: list[str]) -> list[int]:
    """Build the `monotone_constraints` list LightGBM expects, ordered to match
    the given feature_columns list."""
    return [ENTRY_MONOTONE_CONSTRAINTS.get(name, 0) for name in columns]
