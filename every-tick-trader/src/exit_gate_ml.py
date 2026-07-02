"""Exit-classifier inference. Mirrors the feature set of
ai/pm_btc_exit/prepare_exit_dataset.py FEATURE_COLUMNS — keep in sync.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional

from config import log

MODEL_PATH = os.getenv(
    "EXIT_MODEL_PATH", "/app/model/pm_btc_exit_model.txt"
)

# MUST match ai/pm_btc_exit/prepare_exit_dataset.py FEATURE_COLUMNS.
FEATURE_COLUMNS: list[str] = [
    "seconds_left", "time_held", "time_frac",
    "current_bid", "bid_above_entry",
    "peak_minus_current", "unrealized_per_share",
    "bid_drift_3s", "bid_drift_10s",
    "own_spread", "own_bid_size_log", "own_ask_size_log",
    "opp_spread", "book_imbalance",
    "btc_ret_30s", "btc_ret_60s", "btc_ret_30m", "sigma_5m",
    "btc_distance_from_entry", "adverse_btc",
    "binance_chainlink_divergence",
    "direction_up",
]

_booster = None
_load_failed = False
# Per-position bid history for velocity features. Keyed by (cid, dir, entry_ts).
_bid_history: dict = {}
_BID_HISTORY_WINDOW = 15.0  # keep up to 15s; we read 3s and 10s lookbacks


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


def _load() -> None:
    global _booster, _load_failed
    if _booster is not None or _load_failed:
        return
    model_path = _resolve_model_path()
    if not model_path.exists():
        log.warning("Exit gate: model file not found at %s", model_path)
        _load_failed = True
        return
    try:
        import lightgbm as lgb
    except ImportError:
        log.warning("Exit gate: lightgbm not installed")
        _load_failed = True
        return
    try:
        _booster = lgb.Booster(model_file=str(model_path))
        log.info(
            "Exit gate: loaded model from %s (%d features)",
            model_path, _booster.num_feature(),
        )
    except Exception as exc:
        log.warning("Exit gate: failed to load model: %s", exc)
        _load_failed = True


def _record_bid(key, now: float, bid: float) -> list:
    hist = _bid_history.setdefault(key, [])
    hist.append((now, bid))
    cutoff = now - (_BID_HISTORY_WINDOW + 5.0)
    while hist and hist[0][0] < cutoff:
        hist.pop(0)
    return hist


def _bid_at_lookback(hist: list, now: float, lookback_s: float, fallback: float) -> float:
    target = now - lookback_s
    best = None
    for ts, bid in hist:
        if ts <= target:
            best = bid
        else:
            break
    return best if best is not None else fallback


def predict_loss_prob(
    ctx,
    pos,
    current_bid: float,
    now: float,
    btc_distance: float,
    adverse_btc: float,
) -> Optional[float]:
    """Return P(eventual exit beats current_bid by ≥ label_drop) ∈ [0, 1].

    None if the model isn't loaded.
    """
    _load()
    if _booster is None:
        return None

    direction_up = pos.direction == "UP"
    entry_ts = float(getattr(pos, "entry_time", 0.0) or 0.0)
    key = (pos.condition_id, pos.direction, entry_ts)
    hist = _record_bid(key, now, current_bid)

    bid_3s_ago = _bid_at_lookback(hist, now, 3.0, current_bid)
    bid_10s_ago = _bid_at_lookback(hist, now, 10.0, current_bid)

    if direction_up:
        own_bid = ctx.up_bid
        own_ask = ctx.up_ask
        own_bid_size = ctx.up_bid_size
        own_ask_size = ctx.up_ask_size
        opp_bid = ctx.down_bid
        opp_ask = ctx.down_ask
    else:
        own_bid = ctx.down_bid
        own_ask = ctx.down_ask
        own_bid_size = ctx.down_bid_size
        own_ask_size = ctx.down_ask_size
        opp_bid = ctx.up_bid
        opp_ask = ctx.up_ask

    own_spread = max(0.0, own_ask - own_bid)
    opp_spread = max(0.0, opp_ask - opp_bid)
    total_size = (own_bid_size or 0.0) + (own_ask_size or 0.0)
    book_imbalance = (
        ((own_bid_size or 0.0) - (own_ask_size or 0.0)) / total_size
        if total_size > 0 else 0.0
    )

    binance_chainlink_divergence = 0.0
    if ctx.binance_price > 0 and ctx.current_price > 0:
        binance_chainlink_divergence = math.log(ctx.binance_price / ctx.current_price)

    # btc_distance_from_entry: + means favorable to position direction
    entry_btc = float(getattr(pos, "entry_btc_price", 0.0) or 0.0)
    btc_dist_entry = 0.0
    if entry_btc > 0 and ctx.current_price > 0:
        log_return = math.log(ctx.current_price / entry_btc)
        btc_dist_entry = log_return if direction_up else -log_return

    # time_held proxy: from pos.entry_seconds_left and ctx.seconds_left
    bar_total_proxy = max(int(getattr(pos, "entry_seconds_left", 300) or 300), 1)
    time_held = max(0.0, float(bar_total_proxy - ctx.seconds_left))
    time_frac = time_held / max(time_held + ctx.seconds_left, 1.0)

    shares = max(float(getattr(pos, "shares", 1.0) or 1.0), 1.0)
    unrealized = (current_bid - pos.entry_price) * shares
    unrealized_per_share = unrealized / shares

    feats = {
        "seconds_left": float(ctx.seconds_left),
        "time_held": time_held,
        "time_frac": time_frac,
        "current_bid": float(current_bid),
        "bid_above_entry": float(current_bid - pos.entry_price),
        "peak_minus_current": float(getattr(pos, "peak_bid", current_bid) - current_bid),
        "unrealized_per_share": float(unrealized_per_share),
        "bid_drift_3s": float(current_bid - bid_3s_ago),
        "bid_drift_10s": float(current_bid - bid_10s_ago),
        "own_spread": float(own_spread),
        "own_bid_size_log": _safe_log1p(own_bid_size),
        "own_ask_size_log": _safe_log1p(own_ask_size),
        "opp_spread": float(opp_spread),
        "book_imbalance": float(book_imbalance),
        "btc_ret_30s": float(ctx.ret_30s),
        "btc_ret_60s": float(ctx.ret_60s),
        "btc_ret_30m": float(getattr(ctx, "ret_30m", 0.0)),
        "sigma_5m": float(ctx.sigma_5m),
        "btc_distance_from_entry": float(btc_dist_entry),
        "adverse_btc": float(adverse_btc),
        "binance_chainlink_divergence": float(binance_chainlink_divergence),
        "direction_up": 1.0 if direction_up else 0.0,
    }

    row = [feats[name] for name in FEATURE_COLUMNS]
    try:
        score = float(_booster.predict([row])[0])
    except Exception as exc:
        log.warning("Exit gate: predict failed: %s", exc)
        return None
    return max(0.0, min(1.0, score))


def reset_position(condition_id: str, direction: str, entry_ts: float = 0.0) -> None:
    """Clear bid history for a position when it closes."""
    _bid_history.pop((condition_id, direction, float(entry_ts or 0.0)), None)
