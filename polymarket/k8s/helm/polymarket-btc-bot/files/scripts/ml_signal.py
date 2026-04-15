"""ML inference helper for the BTC 5m bot.

Loads a LightGBM booster (trained by ai/pm_btc/) and exposes a single
`predict_p_up` helper.

Contract:
- If the model file is missing or lightgbm isn't installed, `predict_p_up`
  returns None and we fall through silently. The bot still works end-to-end.
- Feature extraction mirrors `ai/pm_btc/features.py` exactly. If you add a
  feature there, add it here too (or refactor to share).
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

from config import log

MODEL_PATH = os.getenv("ML_MODEL_PATH", "/app/model/pm_btc_model.txt")

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

_booster = None  # lazy, cached on first call
_load_failed = False


def _safe_log1p(x: Optional[float]) -> float:
    if x is None or not math.isfinite(x) or x < 0:
        return 0.0
    return math.log1p(x)


def _imbalance(bid_sz: float, ask_sz: float) -> float:
    total = (bid_sz or 0.0) + (ask_sz or 0.0)
    if total <= 0:
        return 0.0
    return ((bid_sz or 0.0) - (ask_sz or 0.0)) / total


def _extract(snapshot: dict[str, Any]) -> Optional[list[float]]:
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
    time_frac = max(0.0, min(1.0, seconds_left / 300.0))
    distance = math.log(current / bar_open) if bar_open > 0 else 0.0

    up_mid = 0.5 * (up_bid + up_ask)
    down_mid = 0.5 * (down_bid + down_ask)
    mid_sum = up_mid + down_mid
    implied_p_up = up_mid / mid_sum if mid_sum > 0 else 0.5

    features = {
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
    return [features[col] for col in FEATURE_COLUMNS]


def _load() -> None:
    global _booster, _load_failed
    if _booster is not None or _load_failed:
        return
    if not os.path.exists(MODEL_PATH):
        log.info("ML signal: model file not found at %s — inference disabled", MODEL_PATH)
        _load_failed = True
        return
    try:
        import lightgbm as lgb
    except ImportError:
        log.info("ML signal: lightgbm not installed — inference disabled")
        _load_failed = True
        return
    try:
        _booster = lgb.Booster(model_file=MODEL_PATH)
        log.info("ML signal: loaded model from %s (%d features)", MODEL_PATH, _booster.num_feature())
    except Exception as exc:
        log.warning("ML signal: failed to load model: %s — inference disabled", exc)
        _load_failed = True


def predict_p_up(snapshot: dict[str, Any]) -> Optional[float]:
    """Return P(bar resolves UP) from the trained model, or None if the model
    isn't available or the snapshot isn't scorable. Never raises."""
    _load()
    if _booster is None:
        return None
    row = _extract(snapshot)
    if row is None:
        return None
    try:
        return float(_booster.predict([row])[0])
    except Exception as exc:
        log.debug("ML signal: predict failed: %s", exc)
        return None
