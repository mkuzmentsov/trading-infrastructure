"""Exit-classifier inference for PM BTC 1h bot.

Loads the v1 LightGBM model trained at `ai/pm_btc_1h_exit/` and exposes
`predict_loss_prob(...)` returning P(loss) ∈ [0, 1]. The model itself
predicts P(win); we return `1 - p_win` so the math_smart.py call site
(which compares p_loss > SMART_EXIT_MODEL_THRESHOLD) keeps its semantics.

Feature schema MUST stay in sync with
`ai/pm_btc_1h_exit/prepare_exit_dataset.py::FEATURE_COLUMNS`.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional

from config import log

MODEL_PATH = os.getenv(
    "EXIT_MODEL_PATH", "/app/model/pm_btc_1h_exit_model.txt"
)

# MUST match ai/pm_btc_1h_exit/prepare_exit_dataset.py::FEATURE_COLUMNS.
FEATURE_COLUMNS: list[str] = [
    "entry_price", "entry_edge", "entry_p_up", "entry_seconds_left",
    "direction_up",
    "time_held", "time_held_frac",
    "seconds_left", "time_frac",
    "current_bid", "bid_minus_entry", "peak_bid", "peak_minus_current",
    "peak_minus_entry", "unrealized", "shares_log",
    "bid_vel_3s", "bid_vel_10s",
    "btc_distance_signed", "btc_distance_abs",
    "btc_ret_30s", "btc_ret_60s", "btc_ret_30m", "sigma_5m",
    "ret_30s_align", "ret_60s_align", "ret_30m_align",
    "adverse_btc",
    "own_spread", "own_bid_size_log", "own_ask_size_log",
    "opp_bid", "book_imbalance",
    "session_pnl", "wr_30min_filled", "wr_30min_known",
]

_booster = None
_load_failed = False

# Per-position bid history for velocity features. Keyed by (cid, dir, entry_ts).
_bid_history: dict = {}
_BID_HISTORY_WINDOW_S = 15.0  # keep up to 15s; we read 3s and 10s lookbacks


def _safe_log1p(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v) or v < 0:
        return 0.0
    return math.log1p(v)


def _resolve_model_path() -> Path:
    """Return path to the model file, preferring a `.gz` sibling if present.

    apply-model-configmap.sh gzips files >= 900 KiB before stuffing them into
    the ConfigMap (K8s ConfigMaps cap at 1 MiB). On the pod, the mounted file
    will have a `.gz` suffix; locally for replay/debug it may be plain.
    """
    path = Path(MODEL_PATH)
    gz = path.with_suffix(path.suffix + ".gz")
    if gz.exists():
        return gz
    if path.exists():
        return path
    # Fallback to chart-local path (useful for replay/debug runs).
    local = Path(__file__).resolve().parent.parent / "model" / path.name
    local_gz = local.with_suffix(local.suffix + ".gz")
    if local_gz.exists():
        return local_gz
    return local


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
        if model_path.suffix == ".gz":
            import gzip
            with gzip.open(model_path, "rt") as fh:
                model_str = fh.read()
            _booster = lgb.Booster(model_str=model_str)
        else:
            _booster = lgb.Booster(model_file=str(model_path))
        log.info(
            "Exit gate: loaded model from %s (%d features expected, %d known)",
            model_path, _booster.num_feature(), len(FEATURE_COLUMNS),
        )
    except Exception as exc:
        log.warning("Exit gate: failed to load model: %s", exc)
        _load_failed = True


def _record_bid(key, now: float, bid: float) -> list:
    hist = _bid_history.setdefault(key, [])
    hist.append((now, bid))
    cutoff = now - (_BID_HISTORY_WINDOW_S + 5.0)
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


def _regime_features() -> tuple[float, float, float]:
    """Return (session_pnl, wr_30min_filled, wr_30min_known) from main module.

    Lazily imports main to avoid a hard circular dependency at module load.
    Defaults to neutral values if main isn't importable yet.
    """
    try:
        import main as _main
    except Exception:
        return 0.0, 0.5, 0.0
    fn = getattr(_main, "_regime_metrics", None)
    if fn is None:
        return 0.0, 0.5, 0.0
    try:
        import time as _time
        m = fn(_time.time())
    except Exception:
        return 0.0, 0.5, 0.0
    session_pnl = float(m.get("session_pnl") or 0.0)
    wr = m.get("wr_30min")
    if wr is None:
        return session_pnl, 0.5, 0.0
    try:
        return session_pnl, float(wr), 1.0
    except (TypeError, ValueError):
        return session_pnl, 0.5, 0.0


def predict_loss_prob(
    ctx,
    pos,
    current_bid: float,
    now: float,
    btc_distance: float,
    adverse_btc: float,
) -> Optional[float]:
    """Return P(eventual close pnl ≤ 0) ∈ [0, 1] given current state.

    None if the model isn't loaded.

    The underlying model predicts P(win) — this function returns 1 − P(win)
    so callers comparing `p_loss > threshold` keep their semantics.
    """
    _load()
    if _booster is None:
        return None

    direction_up = 1 if pos.direction == "UP" else 0
    direction_sign = 1.0 if direction_up else -1.0

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
    else:
        own_bid = ctx.down_bid
        own_ask = ctx.down_ask
        own_bid_size = ctx.down_bid_size
        own_ask_size = ctx.down_ask_size
        opp_bid = ctx.up_bid

    own_spread = max(0.0, (own_ask or 0.0) - (own_bid or 0.0))
    total_size = (own_bid_size or 0.0) + (own_ask_size or 0.0)
    book_imbalance = (
        ((own_bid_size or 0.0) - (own_ask_size or 0.0)) / total_size
        if total_size > 0 else 0.0
    )

    # BTC distance — match prepare_exit_dataset.py: linear return from bar_open,
    # then direction-adjusted (positive = with our bet).
    bar_open = getattr(ctx, "bar_open", 0.0) or 0.0
    current_price = getattr(ctx, "current_price", 0.0) or 0.0
    if bar_open > 0:
        linear_ret = (current_price - bar_open) / bar_open
    else:
        linear_ret = 0.0
    btc_distance_signed = linear_ret * direction_sign
    btc_distance_abs = abs(linear_ret)

    ret_30s = float(getattr(ctx, "ret_30s", 0.0) or 0.0)
    ret_60s = float(getattr(ctx, "ret_60s", 0.0) or 0.0)
    ret_30m = float(getattr(ctx, "ret_30m", 0.0) or 0.0)
    sigma_5m = float(getattr(ctx, "sigma_5m", 0.0) or 0.0)

    entry_seconds_left = int(getattr(pos, "entry_seconds_left", 3600) or 3600)
    seconds_left = int(getattr(ctx, "seconds_left", 0) or 0)
    time_held = max(0.0, float(entry_seconds_left - seconds_left))
    time_held_frac = time_held / max(1.0, float(entry_seconds_left))
    time_frac = float(seconds_left) / 3600.0

    shares = float(getattr(pos, "shares", 0.0) or 0.0)
    entry_price = float(getattr(pos, "entry_price", 0.0) or 0.0)
    peak_bid = float(getattr(pos, "peak_bid", current_bid) or current_bid)
    unrealized = (current_bid - entry_price) * shares

    session_pnl, wr_30min_filled, wr_30min_known = _regime_features()

    feats = {
        "entry_price": entry_price,
        "entry_edge": float(getattr(pos, "entry_edge", 0.0) or 0.0),
        "entry_p_up": float(getattr(pos, "entry_p_up", 0.0) or 0.0),
        "entry_seconds_left": float(entry_seconds_left),
        "direction_up": float(direction_up),
        "time_held": time_held,
        "time_held_frac": time_held_frac,
        "seconds_left": float(seconds_left),
        "time_frac": time_frac,
        "current_bid": float(current_bid),
        "bid_minus_entry": float(current_bid - entry_price),
        "peak_bid": peak_bid,
        "peak_minus_current": peak_bid - current_bid,
        "peak_minus_entry": peak_bid - entry_price,
        "unrealized": unrealized,
        "shares_log": _safe_log1p(shares),
        "bid_vel_3s": float(current_bid - bid_3s_ago) if bid_3s_ago > 0 else 0.0,
        "bid_vel_10s": float(current_bid - bid_10s_ago) if bid_10s_ago > 0 else 0.0,
        "btc_distance_signed": btc_distance_signed,
        "btc_distance_abs": btc_distance_abs,
        "btc_ret_30s": ret_30s,
        "btc_ret_60s": ret_60s,
        "btc_ret_30m": ret_30m,
        "sigma_5m": sigma_5m,
        "ret_30s_align": ret_30s * direction_sign,
        "ret_60s_align": ret_60s * direction_sign,
        "ret_30m_align": ret_30m * direction_sign,
        "adverse_btc": float(adverse_btc),
        "own_spread": own_spread,
        "own_bid_size_log": _safe_log1p(own_bid_size),
        "own_ask_size_log": _safe_log1p(own_ask_size),
        "opp_bid": float(opp_bid or 0.0),
        "book_imbalance": book_imbalance,
        "session_pnl": session_pnl,
        "wr_30min_filled": wr_30min_filled,
        "wr_30min_known": wr_30min_known,
    }

    row = [feats[name] for name in FEATURE_COLUMNS]
    try:
        p_win = float(_booster.predict([row])[0])
    except Exception as exc:
        log.warning("Exit gate: predict failed: %s", exc)
        return None
    p_win = max(0.0, min(1.0, p_win))
    return 1.0 - p_win


def reset_position(condition_id: str, direction: str, entry_ts: float = 0.0) -> None:
    """Clear bid history for a position when it closes."""
    _bid_history.pop((condition_id, direction, float(entry_ts or 0.0)), None)
