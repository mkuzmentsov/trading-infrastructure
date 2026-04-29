from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional

from config import log

MODEL_PATH = os.getenv("ENTRY_GATE_MODEL_PATH", "/app/model/pm_btc_entry_gate_model.txt")

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

_booster = None
_load_failed = False


def _resolve_model_path() -> Path:
    path = Path(MODEL_PATH)
    if path.exists():
        return path
    local_candidate = Path(__file__).resolve().parent.parent / "model" / path.name
    return local_candidate


def _safe_log1p(value: float) -> float:
    if value is None or not math.isfinite(value) or value < 0:
        return 0.0
    return math.log1p(value)


def _imbalance(bid_sz: float, ask_sz: float) -> float:
    total = (bid_sz or 0.0) + (ask_sz or 0.0)
    if total <= 0:
        return 0.0
    return ((bid_sz or 0.0) - (ask_sz or 0.0)) / total


def _load() -> None:
    global _booster, _load_failed
    if _booster is not None or _load_failed:
        return
    model_path = _resolve_model_path()
    if not model_path.exists():
        log.warning("Entry gate: model file not found at %s", model_path)
        _load_failed = True
        return
    try:
        import lightgbm as lgb
    except ImportError:
        log.warning("Entry gate: lightgbm not installed")
        _load_failed = True
        return
    try:
        _booster = lgb.Booster(model_file=str(model_path))
        log.info("Entry gate: loaded model from %s (%d features)", model_path, _booster.num_feature())
    except Exception as exc:
        log.warning("Entry gate: failed to load model: %s", exc)
        _load_failed = True


def predict_entry_score(ctx, signal) -> Optional[float]:
    _load()
    if _booster is None:
        return None

    action = signal.action
    if action not in {"BUY_UP", "BUY_DOWN"}:
        return None

    direction_up = action == "BUY_UP"
    side_bid = ctx.up_bid if direction_up else ctx.down_bid
    side_ask = ctx.up_ask if direction_up else ctx.down_ask
    side_bid_size = ctx.up_bid_size if direction_up else ctx.down_bid_size
    side_ask_size = ctx.up_ask_size if direction_up else ctx.down_ask_size
    debug = signal.debug or {}

    time_frac = max(0.0, min(1.0, ctx.seconds_left / 300.0))
    btc_distance = math.log(ctx.current_price / ctx.bar_open) if ctx.bar_open > 0 and ctx.current_price > 0 else 0.0
    up_mid = 0.5 * (ctx.up_bid + ctx.up_ask)
    down_mid = 0.5 * (ctx.down_bid + ctx.down_ask)
    total = up_mid + down_mid
    implied_p_up = up_mid / total if total > 0 else 0.5
    best_price = ctx.binance_price if ctx.binance_price > 0 else ctx.current_price
    binance_distance = math.log(best_price / ctx.bar_open) if ctx.bar_open > 0 and best_price > 0 else 0.0
    chainlink_distance = math.log(ctx.current_price / ctx.bar_open) if ctx.bar_open > 0 and ctx.current_price > 0 else 0.0

    signal_side_edge = float(debug.get("net_up" if direction_up else "net_down", signal.edge))
    signal_opposite_edge = float(debug.get("net_down" if direction_up else "net_up", 0.0))

    features = {
        "seconds_left": float(ctx.seconds_left),
        "time_frac": float(time_frac),
        "btc_ret_30s": float(ctx.ret_30s),
        "btc_ret_60s": float(ctx.ret_60s),
        "btc_sigma_5m": float(ctx.sigma_5m),
        "btc_distance_from_open": float(btc_distance),
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
        "candidate_mark_to_market": float(side_bid - (signal.price or side_ask)),
        "candidate_ask_size_log": _safe_log1p(side_ask_size),
        "candidate_bid_size_log": _safe_log1p(side_bid_size),
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
    }
    row = [[features[col] for col in FEATURE_COLUMNS]]
    try:
        return float(_booster.predict(row)[0])
    except Exception as exc:
        log.debug("Entry gate: predict failed: %s", exc)
        return None
