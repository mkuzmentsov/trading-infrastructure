from __future__ import annotations

import json
import math
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from config import log

MODEL_PATH = os.getenv("BTC_NEXT_BAR_MODEL_PATH", "/app/model/pm_btc_binance_next_bar_model.txt")
META_PATH = os.getenv("BTC_NEXT_BAR_META_PATH", "/app/model/pm_btc_binance_next_bar_meta.json")
PRIOR_BLEND_WEIGHT = float(os.getenv("BTC_NEXT_BAR_BLEND_WEIGHT", "0.35"))

MIN_HISTORY_BARS = 24
EPS = 1e-12

FEATURE_COLUMNS: list[str] = [
    "ret_cc_1",
    "ret_cc_3",
    "ret_cc_6",
    "ret_cc_12",
    "ret_cc_24",
    "ret_oc_1",
    "ret_oc_3_mean",
    "ret_oc_6_mean",
    "ret_oc_12_mean",
    "range_1",
    "range_3_mean",
    "range_6_mean",
    "range_12_mean",
    "body_1",
    "body_3_mean",
    "body_6_mean",
    "body_12_mean",
    "close_pos_1",
    "upper_wick_1",
    "lower_wick_1",
    "vol_cc_3",
    "vol_cc_6",
    "vol_cc_12",
    "vol_cc_24",
    "up_frac_3",
    "up_frac_6",
    "up_frac_12",
    "close_vs_sma_3",
    "close_vs_sma_6",
    "close_vs_sma_12",
    "close_vs_sma_24",
    "range_expansion_1_6",
    "body_accel_1_3",
    "trend_strength_6",
    "trend_strength_12",
    "trend_strength_24",
    "volume_log_1",
    "volume_ratio_3",
    "volume_ratio_12",
    "quote_volume_ratio_3",
    "trade_count_log_1",
    "trade_count_ratio_3",
    "avg_trade_size_log_1",
    "taker_buy_ratio_3",
    "taker_buy_ratio_12",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
]

_booster = None
_meta: dict | None = None
_load_failed = False


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.exists():
        return path
    return Path(__file__).resolve().parent.parent / "model" / path.name


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den is None or abs(den) <= EPS:
        return default
    return num / den


def _log_ratio(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return math.log(a / b)


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return float(sum(items) / len(items))


def _std(values: Iterable[float]) -> float:
    items = list(values)
    n = len(items)
    if n < 2:
        return 0.0
    mean = _mean(items)
    var = sum((v - mean) ** 2 for v in items) / (n - 1)
    return math.sqrt(max(var, 0.0))


def _bar_body(bar: dict) -> float:
    return _log_ratio(float(bar["close"]), float(bar["open"]))


def _bar_range(bar: dict) -> float:
    high = float(bar["high"])
    low = float(bar["low"])
    open_price = float(bar["open"])
    return _safe_div(high - low, open_price)


def _bar_close_pos(bar: dict) -> float:
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    return _safe_div(close - low, high - low, default=0.5)


def _bar_upper_wick(bar: dict) -> float:
    high = float(bar["high"])
    open_price = float(bar["open"])
    close = float(bar["close"])
    return _safe_div(high - max(open_price, close), high - float(bar["low"]))


def _bar_lower_wick(bar: dict) -> float:
    low = float(bar["low"])
    open_price = float(bar["open"])
    close = float(bar["close"])
    return _safe_div(min(open_price, close) - low, float(bar["high"]) - low)


def _bar_value(bar: dict, key: str) -> float:
    try:
        value = float(bar.get(key, 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return value


def build_feature_row(completed_bars: list[dict], market_start_ts: int | None = None) -> Optional[dict[str, float]]:
    if len(completed_bars) < MIN_HISTORY_BARS:
        return None

    bars = completed_bars[-MAX_HISTORY_BARS:] if len(completed_bars) > MAX_HISTORY_BARS else completed_bars
    closes = [float(bar["close"]) for bar in bars]
    opens = [float(bar["open"]) for bar in bars]
    bodies = [_bar_body(bar) for bar in bars]
    ranges = [_bar_range(bar) for bar in bars]
    volumes = [_bar_value(bar, "volume") for bar in bars]
    quote_volumes = [_bar_value(bar, "quote_volume") for bar in bars]
    trade_counts = [_bar_value(bar, "trade_count") for bar in bars]
    taker_buy_volumes = [_bar_value(bar, "taker_buy_volume") for bar in bars]
    cc_rets = [_log_ratio(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    last = bars[-1]
    close_last = closes[-1]

    def mean_last(items: list[float], n: int) -> float:
        return _mean(items[-n:]) if len(items) >= n else 0.0

    def std_last(items: list[float], n: int) -> float:
        return _std(items[-n:]) if len(items) >= n else 0.0

    def up_frac_last(n: int) -> float:
        return _mean([1.0 if body > 0 else 0.0 for body in bodies[-n:]]) if len(bodies) >= n else 0.5

    def close_vs_sma(n: int) -> float:
        if len(closes) < n:
            return 0.0
        return _safe_div(close_last, _mean(closes[-n:])) - 1.0

    def trend_strength(n: int) -> float:
        if len(closes) < n + 1:
            return 0.0
        return _safe_div(_log_ratio(closes[-1], closes[-(n + 1)]), std_last(cc_rets, n) + EPS)

    def mean_or_zero(items: list[float], n: int) -> float:
        return _mean(items[-n:]) if len(items) >= n else 0.0

    def volume_ratio(n_short: int, n_long: int) -> float:
        if len(volumes) < n_long:
            return 0.0
        return _safe_div(mean_or_zero(volumes, n_short), mean_or_zero(volumes, n_long) + EPS) - 1.0

    def quote_volume_ratio(n_short: int, n_long: int) -> float:
        if len(quote_volumes) < n_long:
            return 0.0
        return _safe_div(mean_or_zero(quote_volumes, n_short), mean_or_zero(quote_volumes, n_long) + EPS) - 1.0

    def trade_count_ratio(n_short: int, n_long: int) -> float:
        if len(trade_counts) < n_long:
            return 0.0
        return _safe_div(mean_or_zero(trade_counts, n_short), mean_or_zero(trade_counts, n_long) + EPS) - 1.0

    def taker_buy_ratio(n: int) -> float:
        if len(volumes) < n:
            return 0.5
        total = sum(volumes[-n:])
        if total <= 0:
            return 0.5
        return max(0.0, min(1.0, sum(taker_buy_volumes[-n:]) / total))

    avg_trade_size_last = _safe_div(volumes[-1], trade_counts[-1] + EPS)

    target_dt = datetime.fromtimestamp(float(market_start_ts or bars[-1]["start_ts"] + 300), tz=timezone.utc)
    hour = target_dt.hour + target_dt.minute / 60.0
    dow = float(target_dt.weekday())

    features = {
        "ret_cc_1": cc_rets[-1] if len(cc_rets) >= 1 else 0.0,
        "ret_cc_3": _log_ratio(closes[-1], closes[-4]) if len(closes) >= 4 else 0.0,
        "ret_cc_6": _log_ratio(closes[-1], closes[-7]) if len(closes) >= 7 else 0.0,
        "ret_cc_12": _log_ratio(closes[-1], closes[-13]) if len(closes) >= 13 else 0.0,
        "ret_cc_24": _log_ratio(closes[-1], closes[-25]) if len(closes) >= 25 else 0.0,
        "ret_oc_1": bodies[-1],
        "ret_oc_3_mean": mean_last(bodies, 3),
        "ret_oc_6_mean": mean_last(bodies, 6),
        "ret_oc_12_mean": mean_last(bodies, 12),
        "range_1": ranges[-1],
        "range_3_mean": mean_last(ranges, 3),
        "range_6_mean": mean_last(ranges, 6),
        "range_12_mean": mean_last(ranges, 12),
        "body_1": bodies[-1],
        "body_3_mean": mean_last(bodies, 3),
        "body_6_mean": mean_last(bodies, 6),
        "body_12_mean": mean_last(bodies, 12),
        "close_pos_1": _bar_close_pos(last),
        "upper_wick_1": _bar_upper_wick(last),
        "lower_wick_1": _bar_lower_wick(last),
        "vol_cc_3": std_last(cc_rets, 3),
        "vol_cc_6": std_last(cc_rets, 6),
        "vol_cc_12": std_last(cc_rets, 12),
        "vol_cc_24": std_last(cc_rets, 24),
        "up_frac_3": up_frac_last(3),
        "up_frac_6": up_frac_last(6),
        "up_frac_12": up_frac_last(12),
        "close_vs_sma_3": close_vs_sma(3),
        "close_vs_sma_6": close_vs_sma(6),
        "close_vs_sma_12": close_vs_sma(12),
        "close_vs_sma_24": close_vs_sma(24),
        "range_expansion_1_6": _safe_div(ranges[-1], mean_last(ranges, 6) + EPS) - 1.0,
        "body_accel_1_3": bodies[-1] - mean_last(bodies, 3),
        "trend_strength_6": trend_strength(6),
        "trend_strength_12": trend_strength(12),
        "trend_strength_24": trend_strength(24),
        "volume_log_1": math.log1p(max(volumes[-1], 0.0)),
        "volume_ratio_3": volume_ratio(3, 12),
        "volume_ratio_12": volume_ratio(12, 24),
        "quote_volume_ratio_3": quote_volume_ratio(3, 12),
        "trade_count_log_1": math.log1p(max(trade_counts[-1], 0.0)),
        "trade_count_ratio_3": trade_count_ratio(3, 12),
        "avg_trade_size_log_1": math.log1p(max(avg_trade_size_last, 0.0)),
        "taker_buy_ratio_3": taker_buy_ratio(3),
        "taker_buy_ratio_12": taker_buy_ratio(12),
        "hour_sin": math.sin(2.0 * math.pi * hour / 24.0),
        "hour_cos": math.cos(2.0 * math.pi * hour / 24.0),
        "dow_sin": math.sin(2.0 * math.pi * dow / 7.0),
        "dow_cos": math.cos(2.0 * math.pi * dow / 7.0),
    }
    return {name: float(features.get(name, 0.0)) for name in FEATURE_COLUMNS}


MAX_HISTORY_BARS = 64


def blend_model_probabilities(
    pm_prob: float | None,
    prior_prob: float | None,
    seconds_left: int,
) -> tuple[float | None, dict[str, float | None]]:
    info: dict[str, float | None] = {
        "pm_prob": pm_prob,
        "prior_prob": prior_prob,
        "prior_weight": 0.0,
        "prior_confidence": 0.0,
    }
    if pm_prob is None and prior_prob is None:
        return None, info
    if pm_prob is None:
        info["prior_weight"] = 1.0
        info["prior_confidence"] = abs((prior_prob or 0.5) - 0.5) * 2.0
        return prior_prob, info
    if prior_prob is None:
        return pm_prob, info

    time_frac = max(0.0, min(1.0, float(seconds_left) / 300.0))
    prior_confidence = max(0.0, min(1.0, abs(prior_prob - 0.5) * 2.0))
    prior_weight = max(0.0, min(0.85, PRIOR_BLEND_WEIGHT * (0.35 + 0.65 * time_frac) * prior_confidence))
    combined = (1.0 - prior_weight) * pm_prob + prior_weight * prior_prob
    info["prior_weight"] = prior_weight
    info["prior_confidence"] = prior_confidence
    return max(0.001, min(0.999, combined)), info


def _load() -> None:
    global _booster, _meta, _load_failed
    if _booster is not None or _load_failed:
        return
    model_path = _resolve_path(MODEL_PATH)
    if not model_path.exists():
        log.info("BTC next-bar prior: model file not found at %s", model_path)
        _load_failed = True
        return
    try:
        import lightgbm as lgb
    except ImportError:
        log.info("BTC next-bar prior: lightgbm not installed")
        _load_failed = True
        return
    try:
        _booster = lgb.Booster(model_file=str(model_path))
        log.info("BTC next-bar prior: loaded model from %s (%d features)", model_path, _booster.num_feature())
    except Exception as exc:
        log.warning("BTC next-bar prior: failed to load model: %s", exc)
        _load_failed = True
        return

    meta_path = _resolve_path(META_PATH)
    if meta_path.exists():
        try:
            _meta = json.loads(meta_path.read_text())
        except Exception as exc:
            log.warning("BTC next-bar prior: failed to load metadata: %s", exc)


def predict_next_bar_p_up(
    completed_bars: list[dict],
    market_start_ts: int | None = None,
) -> Optional[float]:
    _load()
    if _booster is None:
        return None
    features = build_feature_row(completed_bars, market_start_ts=market_start_ts)
    if features is None:
        return None
    row = [[features[name] for name in FEATURE_COLUMNS]]
    try:
        return float(_booster.predict(row)[0])
    except Exception as exc:
        log.debug("BTC next-bar prior: predict failed: %s", exc)
        return None


def model_metadata() -> dict | None:
    _load()
    return _meta


class BinanceBarHistory:
    def __init__(self, max_completed_bars: int = 512) -> None:
        self._completed: deque[dict] = deque(maxlen=max_completed_bars)
        self._current: dict | None = None

    def update(
        self,
        ts: float,
        price: float,
        quantity: float = 0.0,
        buyer_is_maker: bool | None = None,
    ) -> None:
        if ts <= 0 or price <= 0:
            return
        bar_start = int(ts // 300) * 300
        quantity = max(float(quantity or 0.0), 0.0)
        quote_volume = price * quantity
        taker_buy_volume = quantity if buyer_is_maker is False else 0.0
        if self._current is None:
            self._current = {
                "start_ts": bar_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
                "quote_volume": quote_volume,
                "trade_count": 1.0 if quantity > 0 else 0.0,
                "taker_buy_volume": taker_buy_volume,
            }
            return
        current_start = int(self._current["start_ts"])
        if bar_start < current_start:
            return
        if bar_start > current_start:
            self._completed.append(dict(self._current))
            self._current = {
                "start_ts": bar_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
                "quote_volume": quote_volume,
                "trade_count": 1.0 if quantity > 0 else 0.0,
                "taker_buy_volume": taker_buy_volume,
            }
            return
        self._current["high"] = max(float(self._current["high"]), price)
        self._current["low"] = min(float(self._current["low"]), price)
        self._current["close"] = price
        self._current["volume"] = float(self._current.get("volume", 0.0)) + quantity
        self._current["quote_volume"] = float(self._current.get("quote_volume", 0.0)) + quote_volume
        self._current["trade_count"] = float(self._current.get("trade_count", 0.0)) + (1.0 if quantity > 0 else 0.0)
        self._current["taker_buy_volume"] = float(self._current.get("taker_buy_volume", 0.0)) + taker_buy_volume

    def completed_bars(self, before_ts: int | None = None, limit: int = MAX_HISTORY_BARS) -> list[dict]:
        if before_ts is None:
            out = list(self._completed)
        else:
            out = [bar for bar in self._completed if int(bar["start_ts"]) < int(before_ts)]
        if limit > 0 and len(out) > limit:
            return out[-limit:]
        return out
