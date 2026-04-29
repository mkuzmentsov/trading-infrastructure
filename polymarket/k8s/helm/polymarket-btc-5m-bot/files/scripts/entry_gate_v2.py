"""v2 entry gate — LightGBM + isotonic calibration + closed-form prior blend.

Feature computation mirrors ai/pm_btc/decision_features_v2.py so the model
sees identical inputs whether called from live pod or replay. Velocity features
require an in-bar history of prior snapshots, supplied via ctx.prior_snapshots.
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_right
from pathlib import Path
from typing import Any, Optional

from config import log
from math_signal import _fair_p_up

MODEL_PATH_V2 = os.getenv("ENTRY_GATE_MODEL_PATH_V2", "/app/model/pm_btc_entry_gate_model_v2.txt")
CALIBRATOR_PATH_V2 = os.getenv(
    "ENTRY_GATE_CALIBRATOR_PATH_V2", "/app/model/pm_btc_entry_gate_calibrator_v2.json"
)

# Must match ai/pm_btc/decision_features_v2.py ENTRY_FEATURE_COLUMNS_V2.
BASE_FEATURE_COLUMNS = [
    "seconds_left", "time_frac", "btc_ret_30s", "btc_ret_60s", "btc_sigma_5m",
    "btc_distance_from_open", "up_ask", "up_bid", "up_spread", "up_ask_size_log",
    "up_bid_size_log", "down_ask", "down_bid", "down_spread", "down_ask_size_log",
    "down_bid_size_log", "book_imbalance_up", "book_imbalance_down",
    "implied_p_up_from_book", "pm_book_events_log", "feed_price_age",
    "feed_up_age", "feed_down_age",
]
EXTRA_COLUMNS_V2 = [
    "direction_up", "candidate_price", "candidate_bid", "candidate_spread",
    "candidate_ask_size_log", "candidate_bid_size_log", "candidate_book_imbalance",
    "signal_p_up", "signal_edge", "signal_side_edge", "signal_opposite_edge",
    "signal_edge_gap", "signal_size", "book_divergence", "price_source_binance",
    "binance_distance_from_open", "binance_chainlink_divergence", "binance_age",
    "up_bid_velocity_5s", "up_bid_velocity_15s", "down_bid_velocity_5s",
    "down_bid_velocity_15s", "candidate_bid_velocity_15s", "book_events_rate_15s",
    "btc_ret_15s", "btc_accel", "divergence_delta_15s",
    "closed_form_p_up", "closed_form_side_prob",
]
FEATURE_COLUMNS_V2 = BASE_FEATURE_COLUMNS + EXTRA_COLUMNS_V2


_booster = None
_calibrator_x: list[float] = []
_calibrator_y: list[float] = []
_load_failed = False


def _resolve_path(env_path: str) -> Path:
    path = Path(env_path)
    if path.exists():
        return path
    return Path(__file__).resolve().parent.parent / "model" / path.name


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return x


def _safe_log1p(v: Any) -> float:
    x = _safe_float(v)
    return math.log1p(x) if x >= 0 else 0.0


def _imbalance(bid_sz: float, ask_sz: float) -> float:
    total = (bid_sz or 0.0) + (ask_sz or 0.0)
    if total <= 0:
        return 0.0
    return ((bid_sz or 0.0) - (ask_sz or 0.0)) / total


def _load() -> None:
    global _booster, _load_failed, _calibrator_x, _calibrator_y
    if _booster is not None or _load_failed:
        return
    model_path = _resolve_path(MODEL_PATH_V2)
    if not model_path.exists():
        log.warning("Entry gate v2: model file not found at %s", model_path)
        _load_failed = True
        return
    try:
        import lightgbm as lgb
    except ImportError:
        log.warning("Entry gate v2: lightgbm not installed")
        _load_failed = True
        return
    try:
        _booster = lgb.Booster(model_file=str(model_path))
        log.info("Entry gate v2: loaded model from %s (%d features)", model_path, _booster.num_feature())
    except Exception as exc:
        log.warning("Entry gate v2: failed to load model: %s", exc)
        _load_failed = True
        return

    calibrator_path = _resolve_path(CALIBRATOR_PATH_V2)
    if calibrator_path.exists():
        try:
            with calibrator_path.open() as handle:
                data = json.load(handle)
            xs = [float(v) for v in data.get("x_thresholds", [])]
            ys = [float(v) for v in data.get("y_thresholds", [])]
            if len(xs) == len(ys) and len(xs) >= 2:
                _calibrator_x = xs
                _calibrator_y = ys
                log.info("Entry gate v2: loaded isotonic calibrator (%d knots)", len(xs))
        except Exception as exc:
            log.warning("Entry gate v2: failed to load calibrator: %s", exc)
    else:
        log.warning("Entry gate v2: calibrator missing at %s — using raw scores", calibrator_path)


def _apply_calibration(raw: float) -> float:
    if not _calibrator_x:
        return raw
    x = raw
    if x <= _calibrator_x[0]:
        return _calibrator_y[0]
    if x >= _calibrator_x[-1]:
        return _calibrator_y[-1]
    idx = bisect_right(_calibrator_x, x)
    x0, x1 = _calibrator_x[idx - 1], _calibrator_x[idx]
    y0, y1 = _calibrator_y[idx - 1], _calibrator_y[idx]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _pm_bid(row: dict[str, Any], direction: str) -> float:
    pm = row.get("pm") or {}
    key = "up_bid" if direction == "UP" else "down_bid"
    return _safe_float(pm.get(key))


def _best_btc_row(row: dict[str, Any]) -> float:
    btc = row.get("btc") or {}
    binance = _safe_float(btc.get("binance_price"))
    if binance > 0:
        return binance
    return _safe_float(btc.get("current_price"))


def _divergence_row(row: dict[str, Any]) -> float:
    btc = row.get("btc") or {}
    bar_open = _safe_float(btc.get("bar_open"))
    best = _best_btc_row(row)
    chainlink = _safe_float(btc.get("current_price"))
    if bar_open <= 0 or best <= 0 or chainlink <= 0:
        return 0.0
    return math.log(best / chainlink)


def _book_events_row(row: dict[str, Any]) -> float:
    pm = row.get("pm") or {}
    return _safe_float(pm.get("book_events"))


def _lookback_snap(
    prior_rows: list[dict[str, Any]],
    now_ts: float,
    target_lookback_secs: float,
) -> Optional[dict[str, Any]]:
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
    dt = current_ts - prior_ts
    return (current_value - accessor(prior_row)) / max(dt, 1.0)


def _build_features(ctx, signal) -> dict[str, float]:
    direction_up = signal.action == "BUY_UP"
    direction = "UP" if direction_up else "DOWN"
    side_bid = ctx.up_bid if direction_up else ctx.down_bid
    side_ask = ctx.up_ask if direction_up else ctx.down_ask
    side_bid_size = ctx.up_bid_size if direction_up else ctx.down_bid_size
    side_ask_size = ctx.up_ask_size if direction_up else ctx.down_ask_size

    debug = signal.debug or {}
    signal_side_edge = float(debug.get("net_up" if direction_up else "net_down", signal.edge))
    signal_opposite_edge = float(debug.get("net_down" if direction_up else "net_up", 0.0))

    time_frac = max(0.0, min(1.0, ctx.seconds_left / 300.0))
    chainlink_distance = (
        math.log(ctx.current_price / ctx.bar_open)
        if ctx.bar_open > 0 and ctx.current_price > 0 else 0.0
    )
    best_price = ctx.binance_price if ctx.binance_price > 0 else ctx.current_price
    binance_distance = (
        math.log(best_price / ctx.bar_open)
        if ctx.bar_open > 0 and best_price > 0 else 0.0
    )
    up_mid = 0.5 * (ctx.up_bid + ctx.up_ask)
    down_mid = 0.5 * (ctx.down_bid + ctx.down_ask)
    mid_sum = up_mid + down_mid
    implied_p_up = up_mid / mid_sum if mid_sum > 0 else 0.5

    # Velocity features need in-bar history. When absent (missing
    # prior_snapshots), all velocities are zero — graceful fallback.
    now_ts = float(getattr(ctx, "ts", 0.0) or 0.0)
    prior_rows = list(getattr(ctx, "prior_snapshots", []) or [])
    prior_5s = _lookback_snap(prior_rows, now_ts, 5.0)
    prior_15s = _lookback_snap(prior_rows, now_ts, 15.0)

    up_vel_5s = _velocity(ctx.up_bid, now_ts, prior_5s, lambda r: _pm_bid(r, "UP"))
    up_vel_15s = _velocity(ctx.up_bid, now_ts, prior_15s, lambda r: _pm_bid(r, "UP"))
    down_vel_5s = _velocity(ctx.down_bid, now_ts, prior_5s, lambda r: _pm_bid(r, "DOWN"))
    down_vel_15s = _velocity(ctx.down_bid, now_ts, prior_15s, lambda r: _pm_bid(r, "DOWN"))
    candidate_vel_15s = up_vel_15s if direction_up else down_vel_15s

    events_rate_15s = _velocity(
        float(ctx.book_events), now_ts, prior_15s, _book_events_row
    )

    prior_best_btc = _best_btc_row(prior_15s) if prior_15s else 0.0
    btc_ret_15s = (
        math.log(best_price / prior_best_btc)
        if (best_price > 0 and prior_best_btc > 0) else 0.0
    )

    btc_accel = ctx.ret_30s - ctx.ret_60s

    current_div = (
        math.log(best_price / ctx.current_price)
        if (best_price > 0 and ctx.current_price > 0) else 0.0
    )
    prior_div = _divergence_row(prior_15s) if prior_15s else 0.0
    divergence_delta_15s = current_div - prior_div

    closed_form_p_up_val = float(
        _fair_p_up(ctx.bar_open, best_price, ctx.sigma_5m, ctx.seconds_left)
    )
    closed_form_side_prob = closed_form_p_up_val if direction_up else (1.0 - closed_form_p_up_val)

    return {
        "seconds_left": float(ctx.seconds_left),
        "time_frac": float(time_frac),
        "btc_ret_30s": float(ctx.ret_30s),
        "btc_ret_60s": float(ctx.ret_60s),
        "btc_sigma_5m": float(ctx.sigma_5m),
        "btc_distance_from_open": float(chainlink_distance),
        "up_ask": float(ctx.up_ask),
        "up_bid": float(ctx.up_bid),
        "up_spread": float(ctx.up_ask - ctx.up_bid),
        "up_ask_size_log": _safe_log1p(ctx.up_ask_size),
        "up_bid_size_log": _safe_log1p(ctx.up_bid_size),
        "down_ask": float(ctx.down_ask),
        "down_bid": float(ctx.down_bid),
        "down_spread": float(ctx.down_ask - ctx.down_bid),
        "down_ask_size_log": _safe_log1p(ctx.down_ask_size),
        "down_bid_size_log": _safe_log1p(ctx.down_bid_size),
        "book_imbalance_up": _imbalance(ctx.up_bid_size, ctx.up_ask_size),
        "book_imbalance_down": _imbalance(ctx.down_bid_size, ctx.down_ask_size),
        "implied_p_up_from_book": float(implied_p_up),
        "pm_book_events_log": _safe_log1p(float(ctx.book_events)),
        "feed_price_age": float(ctx.feed_price_age),
        "feed_up_age": float(ctx.feed_up_age),
        "feed_down_age": float(ctx.feed_down_age),
        "direction_up": 1.0 if direction_up else 0.0,
        "candidate_price": float(signal.price or side_ask),
        "candidate_bid": float(side_bid),
        "candidate_spread": float(side_ask - side_bid),
        "candidate_ask_size_log": _safe_log1p(side_ask_size),
        "candidate_bid_size_log": _safe_log1p(side_bid_size),
        "candidate_book_imbalance": _imbalance(side_bid_size, side_ask_size),
        "signal_p_up": float(signal.p_up),
        "signal_edge": float(signal.edge),
        "signal_side_edge": float(signal_side_edge),
        "signal_opposite_edge": float(signal_opposite_edge),
        "signal_edge_gap": float(signal_side_edge - signal_opposite_edge),
        "signal_size": float(signal.size),
        "book_divergence": float(debug.get("book_divergence", 0.0)),
        "price_source_binance": 1.0 if debug.get("price_source") == "binance" else 0.0,
        "binance_distance_from_open": float(binance_distance),
        "binance_chainlink_divergence": float(binance_distance - chainlink_distance),
        "binance_age": float(ctx.binance_age),
        "up_bid_velocity_5s": float(up_vel_5s),
        "up_bid_velocity_15s": float(up_vel_15s),
        "down_bid_velocity_5s": float(down_vel_5s),
        "down_bid_velocity_15s": float(down_vel_15s),
        "candidate_bid_velocity_15s": float(candidate_vel_15s),
        "book_events_rate_15s": float(events_rate_15s),
        "btc_ret_15s": float(btc_ret_15s),
        "btc_accel": float(btc_accel),
        "divergence_delta_15s": float(divergence_delta_15s),
        "closed_form_p_up": float(closed_form_p_up_val),
        "closed_form_side_prob": float(closed_form_side_prob),
    }


def predict_entry_score_v2(ctx, signal) -> Optional[dict[str, float]]:
    """Return {raw, calibrated, closed_form_side_prob, blended} or None on failure.
    Caller chooses which score to gate on (blended is preferred)."""
    _load()
    if _booster is None:
        return None
    if signal.action not in {"BUY_UP", "BUY_DOWN"}:
        return None
    try:
        features = _build_features(ctx, signal)
    except Exception as exc:
        log.debug("Entry gate v2: feature build failed: %s", exc)
        return None
    row = [[features[col] for col in FEATURE_COLUMNS_V2]]
    try:
        raw = float(_booster.predict(row)[0])
    except Exception as exc:
        log.debug("Entry gate v2: predict failed: %s", exc)
        return None
    calibrated = float(_apply_calibration(raw))
    closed_form_side = float(features["closed_form_side_prob"])
    return {
        "raw": raw,
        "calibrated": calibrated,
        "closed_form_side_prob": closed_form_side,
    }
