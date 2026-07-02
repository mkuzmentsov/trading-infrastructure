#!/usr/bin/env python3
"""
Shared bar/snapshot parsing and reporting helpers for the Polymarket BTC bot.

The replay engine lives in `files/scripts/strategies/bundle_backtest.py`.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def apply_yaml_to_env(yaml_path: str) -> None:
    """Export the `bot` section of a helm values.yaml to os.environ.

    Replay-critical: must run BEFORE strategies/config/math_signal are imported,
    since those modules freeze env-driven thresholds at module load time.
    Helm YAML keys are camelCase; config.py reads SCREAMING_SNAKE_CASE env vars,
    so convert automatically.
    """
    with open(yaml_path) as handle:
        raw = yaml.safe_load(handle) or {}
    bot = raw.get("bot", {}) or {}
    for yaml_key, value in bot.items():
        if value is None:
            continue
        env_key = _CAMEL_TO_SNAKE_RE.sub("_", yaml_key).upper()
        # Caller-supplied env wins over YAML (lets CLI sweeps override).
        if env_key in os.environ:
            continue
        os.environ[env_key] = str(value)


# ── Signal model (self-contained, mirrors math_signal.py) ────────────────────

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


ENTRY_GATE_FEATURE_COLUMNS: list[str] = [
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

_entry_gate_boosters: dict[str, object | None] = {}
_entry_gate_failures: set[str] = set()


def _safe_log1p(value: float) -> float:
    if value is None or not math.isfinite(value) or value < 0:
        return 0.0
    return math.log1p(value)


def _imbalance(bid_sz: float, ask_sz: float) -> float:
    total = (bid_sz or 0.0) + (ask_sz or 0.0)
    if total <= 0:
        return 0.0
    return ((bid_sz or 0.0) - (ask_sz or 0.0)) / total


def _resolve_entry_gate_model_path(model_path: str) -> Path:
    path = Path(model_path)
    if path.exists():
        return path
    local_candidate = Path(__file__).resolve().parent / "files" / "model" / path.name
    return local_candidate


def _load_entry_gate_booster(model_path: str):
    resolved = str(_resolve_entry_gate_model_path(model_path))
    if resolved in _entry_gate_boosters:
        return _entry_gate_boosters[resolved]
    if resolved in _entry_gate_failures:
        return None
    path = Path(resolved)
    if not path.exists():
        _entry_gate_failures.add(resolved)
        return None
    try:
        import lightgbm as lgb
    except Exception:
        _entry_gate_failures.add(resolved)
        return None
    try:
        booster = lgb.Booster(model_file=str(path))
    except Exception:
        _entry_gate_failures.add(resolved)
        return None
    _entry_gate_boosters[resolved] = booster
    return booster


def predict_entry_gate_score(cfg: dict, snap: dict, signal: Signal) -> Optional[float]:
    booster = _load_entry_gate_booster(cfg["ENTRY_GATE_MODEL_PATH"])
    if booster is None:
        return None

    action = signal.action
    if action not in {"BUY_UP", "BUY_DOWN"}:
        return None

    btc = snap.get("btc", {})
    pm = snap.get("pm", {})
    feeds = snap.get("feeds", {})
    staleness = feeds.get("staleness", {})

    direction_up = action == "BUY_UP"
    up_bid = float(pm.get("up_bid", 0.0))
    up_ask = float(pm.get("up_ask", 0.0))
    down_bid = float(pm.get("down_bid", 0.0))
    down_ask = float(pm.get("down_ask", 0.0))
    up_bid_size = float(pm.get("up_bid_size", 0.0))
    up_ask_size = float(pm.get("up_ask_size", 0.0))
    down_bid_size = float(pm.get("down_bid_size", 0.0))
    down_ask_size = float(pm.get("down_ask_size", 0.0))
    side_bid = up_bid if direction_up else down_bid
    side_ask = up_ask if direction_up else down_ask
    side_bid_size = up_bid_size if direction_up else down_bid_size
    side_ask_size = up_ask_size if direction_up else down_ask_size
    current_price = float(btc.get("current_price", 0.0))
    bar_open = float(btc.get("bar_open", 0.0))
    binance_price = float(btc.get("binance_price") or 0.0)
    best_price = binance_price if binance_price > 0 else current_price
    debug = signal.debug or {}

    time_frac = max(0.0, min(1.0, float(snap.get("seconds_left", 0.0)) / 300.0))
    btc_distance = math.log(current_price / bar_open) if bar_open > 0 and current_price > 0 else 0.0
    up_mid = 0.5 * (up_bid + up_ask)
    down_mid = 0.5 * (down_bid + down_ask)
    total = up_mid + down_mid
    implied_p_up = up_mid / total if total > 0 else 0.5
    binance_distance = math.log(best_price / bar_open) if bar_open > 0 and best_price > 0 else 0.0
    chainlink_distance = math.log(current_price / bar_open) if bar_open > 0 and current_price > 0 else 0.0
    signal_side_edge = float(debug.get("net_up" if direction_up else "net_down", signal.edge))
    signal_opposite_edge = float(debug.get("net_down" if direction_up else "net_up", 0.0))

    features = {
        "seconds_left": float(snap.get("seconds_left", 0.0)),
        "time_frac": float(time_frac),
        "btc_ret_30s": float(btc.get("ret_30s", 0.0)),
        "btc_ret_60s": float(btc.get("ret_60s", 0.0)),
        "btc_sigma_5m": float(btc.get("sigma_5m", 0.0)),
        "btc_distance_from_open": float(btc_distance),
        "up_ask": up_ask,
        "up_bid": up_bid,
        "up_spread": float(up_ask - up_bid),
        "up_ask_size_log": _safe_log1p(up_ask_size),
        "up_bid_size_log": _safe_log1p(up_bid_size),
        "down_ask": down_ask,
        "down_bid": down_bid,
        "down_spread": float(down_ask - down_bid),
        "down_ask_size_log": _safe_log1p(down_ask_size),
        "down_bid_size_log": _safe_log1p(down_bid_size),
        "book_imbalance_up": _imbalance(up_bid_size, up_ask_size),
        "book_imbalance_down": _imbalance(down_bid_size, down_ask_size),
        "implied_p_up_from_book": float(implied_p_up),
        "pm_book_events_log": _safe_log1p(float(pm.get("book_events", 0.0))),
        "feed_price_age": float(staleness.get("price_age", 0.0)),
        "feed_up_age": float(staleness.get("pm_up_age", 0.0)),
        "feed_down_age": float(staleness.get("pm_down_age", 0.0)),
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
        "binance_age": float(btc.get("binance_age", 0.0) or 0.0),
    }
    row = [[features[col] for col in ENTRY_GATE_FEATURE_COLUMNS]]
    try:
        return float(booster.predict(row)[0])
    except Exception:
        return None


def apply_entry_strategy(cfg: dict, snap: dict, signal: Signal) -> Signal:
    if cfg["STRATEGY_NAME"] not in {"pm_btc_ml-entry", "pm_btc_ml-entry-v2"}:
        return signal
    if signal.action not in {"BUY_UP", "BUY_DOWN"}:
        return signal

    gate_score = predict_entry_gate_score(cfg, snap, signal)
    signal.debug["entry_gate_score"] = round(gate_score, 4) if gate_score is not None else None
    if gate_score is None:
        return Signal("NO_TRADE", None, 0, signal.p_up, signal.edge, "Entry gate model unavailable", signal.debug)
    if gate_score < cfg["ENTRY_GATE_THRESHOLD"]:
        return Signal(
            "NO_TRADE",
            None,
            0,
            signal.p_up,
            signal.edge,
            f"Entry gate below threshold ({gate_score:.3f} < {cfg['ENTRY_GATE_THRESHOLD']:.3f})",
            signal.debug,
        )

    price = float(signal.price or 0.0)
    if price < cfg["ENTRY_GATE_MIN_PRICE"]:
        cheap_override = (
            gate_score >= cfg["ENTRY_GATE_CHEAP_OVERRIDE_SCORE"]
            and signal.edge >= cfg["ENTRY_GATE_CHEAP_OVERRIDE_EDGE"]
        )
        signal.debug["cheap_override"] = cheap_override
        if not cheap_override:
            return Signal(
                "NO_TRADE",
                None,
                0,
                signal.p_up,
                signal.edge,
                (
                    f"Cheap entry veto (price={price:.3f} < {cfg['ENTRY_GATE_MIN_PRICE']:.3f}, "
                    f"score={gate_score:.3f}, edge={signal.edge:.3f})"
                ),
                signal.debug,
            )
    return signal


def generate_signal(
    cfg: dict,
    cash_amount: float,
    seconds_left: int,
    bar_open: float,
    current_price: float,
    sigma_5m: float,
    up_bid: float,
    up_ask: float,
    down_bid: float,
    down_ask: float,
    binance_price: float = 0.0,
) -> Signal:
    """Re-implementation of math_signal.generate_signal using config dict."""

    MIN_EDGE = cfg["MIN_EDGE"]
    TAKER_FEE_BPS = cfg["TAKER_FEE_BPS"]
    MAX_ENTRY_SPREAD = cfg["MAX_ENTRY_SPREAD"]
    MIN_ENTRY_PRICE = cfg["MIN_ENTRY_PRICE"]
    MAX_ENTRY_PRICE = cfg["MAX_ENTRY_PRICE"]
    MODEL_PROB_FLOOR = cfg["MODEL_PROB_FLOOR"]
    MODEL_PROB_CEIL = cfg["MODEL_PROB_CEIL"]
    BET_SIZE_MIN = cfg["BET_SIZE_MIN"]
    BET_SIZE_MAX = cfg["BET_SIZE_MAX"]
    MAX_BUDGET_FRACTION = cfg["MAX_BUDGET_FRACTION"]
    MIN_POSITION_SHARES = cfg["MIN_POSITION_SHARES"]
    MIN_BTC_DISTANCE = cfg["MIN_BTC_DISTANCE"]
    MIN_BOOK_DIVERGENCE = cfg["MIN_BOOK_DIVERGENCE"]
    LATE_ENTRY_SECS = cfg["LATE_ENTRY_SECS"]
    LATE_ENTRY_EDGE_DISCOUNT = cfg["LATE_ENTRY_EDGE_DISCOUNT"]
    FILTER_CONTRARIAN_ENTRIES = cfg["FILTER_CONTRARIAN_ENTRIES"]
    CONTRARIAN_TAIL_MAX_PRICE = cfg["CONTRARIAN_TAIL_MAX_PRICE"]
    CONTRARIAN_MOVE_FILTER = cfg["CONTRARIAN_MOVE_FILTER"]

    def _no_trade(reason, p_up_value=0.5, edge_value=0.0, **kw):
        return Signal("NO_TRADE", None, 0, round(p_up_value, 4), round(edge_value, 4), reason, kw)

    if seconds_left < 10:
        return _no_trade("Too little time left")
    if bar_open <= 0 or current_price <= 0:
        return _no_trade("Missing BTC prices")
    if not (0 < up_bid <= up_ask < 1 and 0 < down_bid <= down_ask < 1):
        return _no_trade("Books not live")

    spread_up = up_ask - up_bid
    spread_down = down_ask - down_bid
    if spread_up > MAX_ENTRY_SPREAD and spread_down > MAX_ENTRY_SPREAD:
        return _no_trade(f"Spread too wide (up={spread_up:.3f}, down={spread_down:.3f})")

    best_price = binance_price if binance_price > 0 else current_price
    price_source = "binance" if binance_price > 0 else "chainlink"

    btc_distance = math.log(best_price / bar_open) if bar_open > 0 and best_price > 0 else 0.0

    # Fair P(UP) — mirrors _fair_p_up()
    distance = math.log(best_price / bar_open)
    time_frac = max(seconds_left / 300.0, 1e-6)
    sigma_rem = max(sigma_5m * math.sqrt(time_frac), 1e-6)
    z = _clip(distance / sigma_rem, -3.0, 3.0)
    raw_p = _norm_cdf(z)
    shrink = 0.92  # hardcoded in math_signal.py, NOT from MODEL_PROB_SHRINK env
    p_up = _clip(0.5 + shrink * (raw_p - 0.5), MODEL_PROB_FLOOR, MODEL_PROB_CEIL)
    p_down = 1.0 - p_up

    # Book implied P(UP)
    up_mid = 0.5 * (up_bid + up_ask)
    down_mid = 0.5 * (down_bid + down_ask)
    total = up_mid + down_mid
    implied = up_mid / total if total > 0 else 0.5
    book_divergence = abs(p_up - implied)

    # Edge
    fee = TAKER_FEE_BPS / 10000.0
    net_up = p_up - up_ask - fee
    net_down = p_down - down_ask - fee

    # Adaptive edge threshold
    edge_threshold = MIN_EDGE
    if seconds_left < LATE_ENTRY_SECS:
        time_ratio = seconds_left / max(LATE_ENTRY_SECS, 1)
        discount = LATE_ENTRY_EDGE_DISCOUNT * (1.0 - time_ratio)
        edge_threshold = MIN_EDGE * (1.0 - discount)

    dbg = dict(
        p_up=round(p_up, 4), p_down=round(p_down, 4),
        net_up=round(net_up, 4), net_down=round(net_down, 4),
        btc_distance=round(btc_distance, 6),
        book_divergence=round(book_divergence, 4),
        book_implied_p_up=round(implied, 4),
        edge_threshold=round(edge_threshold, 4),
        price_source=price_source,
        best_price=round(best_price, 2),
        seconds_left=seconds_left,
        sigma_5m=round(sigma_5m, 6),
        spread_up=round(spread_up, 4),
        spread_down=round(spread_down, 4),
    )

    # Filter 1: BTC distance
    if abs(btc_distance) < MIN_BTC_DISTANCE:
        return _no_trade(
            f"BTC too close to open (dist={btc_distance:+.5f})",
            p_up_value=p_up, edge_value=max(net_up, net_down), **dbg,
        )

    # Filter 2: Book divergence
    if book_divergence < MIN_BOOK_DIVERGENCE:
        return _no_trade(
            f"Book already priced in (div={book_divergence:.4f})",
            p_up_value=p_up, edge_value=max(net_up, net_down), **dbg,
        )

    # Tradeability
    up_tradeable = MIN_ENTRY_PRICE <= up_ask <= MAX_ENTRY_PRICE and spread_up <= MAX_ENTRY_SPREAD
    down_tradeable = MIN_ENTRY_PRICE <= down_ask <= MAX_ENTRY_PRICE and spread_down <= MAX_ENTRY_SPREAD

    if net_up >= net_down and net_up >= edge_threshold and up_tradeable:
        action, price, p, edge = "BUY_UP", up_ask, p_up, net_up
    elif net_down > net_up and net_down >= edge_threshold and down_tradeable:
        action, price, p, edge = "BUY_DOWN", down_ask, p_down, net_down
    else:
        return _no_trade(f"No edge above threshold ({edge_threshold:.4f})",
                         p_up_value=p_up, edge_value=max(net_up, net_down), **dbg)

    if FILTER_CONTRARIAN_ENTRIES:
        is_contrarian_up = action == "BUY_UP" and btc_distance < 0
        is_contrarian_down = action == "BUY_DOWN" and btc_distance > 0
        if is_contrarian_up or is_contrarian_down:
            side = "UP" if is_contrarian_up else "DOWN"
            if abs(btc_distance) > CONTRARIAN_MOVE_FILTER:
                return _no_trade(
                    f"Contrarian {side} blocked (dist={btc_distance:+.5f})",
                    p_up_value=p_up,
                    edge_value=edge,
                    **dbg,
                )
            if price > CONTRARIAN_TAIL_MAX_PRICE:
                return _no_trade(
                    f"Contrarian {side} too expensive (ask={price:.3f})",
                    p_up_value=p_up,
                    edge_value=edge,
                    **dbg,
                )

    budget = min(cash_amount * MAX_BUDGET_FRACTION, BET_SIZE_MAX)
    if budget < BET_SIZE_MIN:
        return _no_trade("Budget below minimum", p_up_value=p_up, edge_value=edge, **dbg)

    size = math.floor(budget / price)
    if size < MIN_POSITION_SHARES:
        return _no_trade(f"Fewer than {MIN_POSITION_SHARES} shares",
                         p_up_value=p_up, edge_value=edge, **dbg)

    return Signal(
        action=action,
        price=round(price, 4),
        size=size,
        p_up=round(p_up, 4),
        edge=round(edge, 4),
        reason=f"fair={p:.3f} mkt={price:.3f} edge={edge:.4f} div={book_divergence:.3f} src={price_source}",
        debug=dbg,
    )


# ── Config loading ───────────────────────────────────────────────────────────

# Map YAML camelCase keys to env var names
YAML_TO_ENV = {
    "minEdge": "MIN_EDGE",
    "costBuffer": "COST_BUFFER",
    "kellyScale": "KELLY_SCALE",
    "takerFeeBps": "TAKER_FEE_BPS",
    "entryMinSecondsLeft": "ENTRY_MIN_SECONDS_LEFT",
    "maxEntrySpread": "MAX_ENTRY_SPREAD",
    "minEntryPrice": "MIN_ENTRY_PRICE",
    "maxEntryPrice": "MAX_ENTRY_PRICE",
    "betSizeMin": "BET_SIZE_MIN",
    "betSizeMax": "BET_SIZE_MAX",
    "maxBudgetFraction": "MAX_BUDGET_FRACTION",
    "minPositionShares": "MIN_POSITION_SHARES",
    "modelProbShrink": "MODEL_PROB_SHRINK",
    "modelProbFloor": "MODEL_PROB_FLOOR",
    "modelProbCeil": "MODEL_PROB_CEIL",
    "strategyName": "STRATEGY_NAME",
    "holdToExpiryDefault": "HOLD_TO_EXPIRY_DEFAULT",
    "minBtcDistance": "MIN_BTC_DISTANCE",
    "minBookDivergence": "MIN_BOOK_DIVERGENCE",
    "lateEntrySecs": "LATE_ENTRY_SECS",
    "lateEntryEdgeDiscount": "LATE_ENTRY_EDGE_DISCOUNT",
    "stopLoss": "STOP_LOSS",
    "takeProfit": "TAKE_PROFIT",
    "signalExitEdge": "SIGNAL_EXIT_EDGE",
    "slArmDelaySecs": "SL_ARM_DELAY_SECS",
    "slMinAdverseBtc": "SL_MIN_ADVERSE_BTC",
    "ultraCheapSlDelaySecs": "ULTRA_CHEAP_SL_DELAY_SECS",
    "thesisMinBtcDistance": "THESIS_MIN_BTC_DISTANCE",
    "trailingArmGain": "TRAILING_ARM_GAIN",
    "trailingStopGap": "TRAILING_STOP_GAP",
    "entryConfirmationTicks": "ENTRY_CONFIRMATION_TICKS",
    "stopLossMarketLimit": "STOP_LOSS_MARKET_LIMIT",
    "filterContrarianEntries": "FILTER_CONTRARIAN_ENTRIES",
    "contrarianTailMaxPrice": "CONTRARIAN_TAIL_MAX_PRICE",
    "contrarianMoveFilter": "CONTRARIAN_MOVE_FILTER",
    "entryGateModelPath": "ENTRY_GATE_MODEL_PATH",
    "entryGateThreshold": "ENTRY_GATE_THRESHOLD",
    "entryGateMinPrice": "ENTRY_GATE_MIN_PRICE",
    "entryGateCheapOverrideScore": "ENTRY_GATE_CHEAP_OVERRIDE_SCORE",
    "entryGateCheapOverrideEdge": "ENTRY_GATE_CHEAP_OVERRIDE_EDGE",
    "mlEntryBaseStopLoss": "ML_ENTRY_BASE_STOP_LOSS",
    "mlEntryLateStopLoss": "ML_ENTRY_LATE_STOP_LOSS",
    "mlEntryLateStopSecs": "ML_ENTRY_LATE_STOP_SECS",
    "mlEntryTrailingArmGain": "ML_ENTRY_TRAILING_ARM_GAIN",
    "mlEntryTrailingGap": "ML_ENTRY_TRAILING_GAP",
    "mlEntryThesisProfitLock": "ML_ENTRY_THESIS_PROFIT_LOCK",
    "mlEntryThesisFloorMin": "ML_ENTRY_THESIS_FLOOR_MIN",
    "mlEntryThesisEntryFraction": "ML_ENTRY_THESIS_ENTRY_FRACTION",
    "mlEntryLateBarCutSecs": "ML_ENTRY_LATE_BAR_CUT_SECS",
    "mlEntryLateBarPositiveSecs": "ML_ENTRY_LATE_BAR_POSITIVE_SECS",
    "mlEntryLateBarPositiveFloor": "ML_ENTRY_LATE_BAR_POSITIVE_FLOOR",
    "mlEntryDominantEdgeFloor": "ML_ENTRY_DOMINANT_EDGE_FLOOR",
    "mlEntryDominantEntryFraction": "ML_ENTRY_DOMINANT_ENTRY_FRACTION",
    "mlEntryForceExitSecs": "ML_ENTRY_FORCE_EXIT_SECS",
}

# Defaults matching config.py
DEFAULTS = {
    "MIN_EDGE": 0.04,
    "COST_BUFFER": 0.02,
    "KELLY_SCALE": 0.5,
    "TAKER_FEE_BPS": 0.0,
    "ENTRY_MIN_SECONDS_LEFT": 60,
    "MAX_ENTRY_SPREAD": 0.04,
    "MIN_ENTRY_PRICE": 0.05,
    "MAX_ENTRY_PRICE": 0.60,
    "BET_SIZE_MIN": 0.50,
    "BET_SIZE_MAX": 5.00,
    "MAX_BUDGET_FRACTION": 0.10,
    "MIN_POSITION_SHARES": 6,
    "MODEL_PROB_SHRINK": 0.65,
    "MODEL_PROB_FLOOR": 0.05,
    "MODEL_PROB_CEIL": 0.95,
    "STRATEGY_NAME": "latency_arb_hold",
    "HOLD_TO_EXPIRY_DEFAULT": True,
    "MIN_BTC_DISTANCE": 0.0004,
    "MIN_BOOK_DIVERGENCE": 0.04,
    "LATE_ENTRY_SECS": 90,
    "LATE_ENTRY_EDGE_DISCOUNT": 0.30,
    "STOP_LOSS": 0.08,
    "TAKE_PROFIT": 0.15,
    "SIGNAL_EXIT_EDGE": 0.05,
    "SL_ARM_DELAY_SECS": 60,
    "SL_MIN_ADVERSE_BTC": 0.0015,
    "ULTRA_CHEAP_SL_DELAY_SECS": 120,
    "THESIS_MIN_BTC_DISTANCE": 0.002,
    "TRAILING_ARM_GAIN": 0.20,
    "TRAILING_STOP_GAP": 0.03,
    "ENTRY_CONFIRMATION_TICKS": 1,
    "STOP_LOSS_MARKET_LIMIT": 1,
    "FILTER_CONTRARIAN_ENTRIES": False,
    "CONTRARIAN_TAIL_MAX_PRICE": 0.25,
    "CONTRARIAN_MOVE_FILTER": 0.0015,
    "ENTRY_GATE_MODEL_PATH": "/app/model/pm_btc_entry_gate_model.txt",
    "ENTRY_GATE_THRESHOLD": 0.55,
    "ENTRY_GATE_MIN_PRICE": 0.30,
    "ENTRY_GATE_CHEAP_OVERRIDE_SCORE": 0.78,
    "ENTRY_GATE_CHEAP_OVERRIDE_EDGE": 0.20,
    "ML_ENTRY_BASE_STOP_LOSS": 0.10,
    "ML_ENTRY_LATE_STOP_LOSS": 0.08,
    "ML_ENTRY_LATE_STOP_SECS": 90,
    "ML_ENTRY_TRAILING_ARM_GAIN": 0.08,
    "ML_ENTRY_TRAILING_GAP": 0.05,
    "ML_ENTRY_THESIS_PROFIT_LOCK": 0.04,
    "ML_ENTRY_THESIS_FLOOR_MIN": 0.02,
    "ML_ENTRY_THESIS_ENTRY_FRACTION": 0.35,
    "ML_ENTRY_LATE_BAR_CUT_SECS": 45,
    "ML_ENTRY_LATE_BAR_POSITIVE_SECS": 25,
    "ML_ENTRY_LATE_BAR_POSITIVE_FLOOR": 0.03,
    "ML_ENTRY_DOMINANT_EDGE_FLOOR": 0.08,
    "ML_ENTRY_DOMINANT_ENTRY_FRACTION": 0.50,
    "ML_ENTRY_FORCE_EXIT_SECS": 10,
}


def load_config(yaml_path: str) -> dict:
    """Load a bot YAML and return a flat config dict with env-var-style keys."""
    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    bot = raw.get("bot", {})
    cfg = dict(DEFAULTS)

    for yaml_key, env_key in YAML_TO_ENV.items():
        if yaml_key in bot:
            val = str(bot[yaml_key])
            default = DEFAULTS.get(env_key)
            if isinstance(default, bool):
                cfg[env_key] = val.lower() == "true"
            elif isinstance(default, int):
                cfg[env_key] = int(val)
            elif isinstance(default, float):
                cfg[env_key] = float(val)
            else:
                cfg[env_key] = val

    return cfg


# ── Snapshot loading ─────────────────────────────────────────────────────────

def load_snapshots(log_dir: str) -> list[dict]:
    """Load and dedup training snapshots from a log directory."""
    jsonl_path = os.path.join(log_dir, "logs-training.jsonl")
    if not os.path.exists(jsonl_path):
        print(f"ERROR: {jsonl_path} not found")
        sys.exit(1)

    snapshots = []
    seen_ts = set()
    bad_lines = 0

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue

            ts = rec.get("ts")
            if ts is None or ts in seen_ts:
                continue
            seen_ts.add(ts)
            snapshots.append(rec)

    snapshots.sort(key=lambda r: r["ts"])
    if bad_lines:
        print(f"  (skipped {bad_lines} malformed lines)")
    return snapshots


# ── Bar grouping & outcome ───────────────────────────────────────────────────

@dataclass
class Bar:
    condition_id: str
    question: str
    snapshots: list[dict] = field(default_factory=list)
    bar_open: float = 0.0
    final_price: float = 0.0
    outcome: str = ""  # "UP" or "DOWN"
    market_end_ts: float = 0.0


def group_bars(snapshots: list[dict]) -> list[Bar]:
    """Group snapshots by condition_id and determine each bar's outcome."""
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for s in snapshots:
        cid = s.get("condition_id", "")
        if cid:
            by_cid[cid].append(s)

    bars = []
    for cid, snaps in by_cid.items():
        snaps.sort(key=lambda s: s["ts"])
        bar = Bar(
            condition_id=cid,
            question=snaps[0].get("question", ""),
            snapshots=snaps,
        )

        # Get bar_open from first snapshot
        btc = snaps[0].get("btc", {})
        bar.bar_open = btc.get("bar_open", 0.0)
        bar.market_end_ts = snaps[0].get("market_end_ts", 0.0)

        # Determine outcome from last snapshot: use binance_price > current_price > bar_open
        last = snaps[-1]
        last_btc = last.get("btc", {})
        final = last_btc.get("binance_price") or last_btc.get("current_price", 0.0)
        bar.final_price = final

        if bar.bar_open > 0 and final > 0:
            bar.outcome = "UP" if final >= bar.bar_open else "DOWN"
        else:
            bar.outcome = ""

        bars.append(bar)

    bars.sort(key=lambda b: b.snapshots[0]["ts"])
    return bars


@dataclass
class Trade:
    ts: float
    condition_id: str
    question: str
    direction: str
    entry_price: float
    shares: int
    edge: float
    p_up: float
    seconds_left: int
    outcome: str
    exit_reason: str
    exit_price: float
    pnl: float
    btc_distance: float
    book_divergence: float
    price_source: str


def _backtest_cli_disabled() -> None:
    raise SystemExit(
        "The generic backtest engine has been removed. "
        "Use files/scripts/strategies/bundle_backtest.py for replay/reporting."
    )


# ── Reporting ────────────────────────────────────────────────────────────────

def print_report(cfg: dict, trades: list[Trade], bars: list[Bar], log_dir: str):
    """Print backtest summary and trade details."""
    total_bars = len([b for b in bars if b.outcome])

    print("\n" + "=" * 80)
    print("BACKTEST REPORT")
    print("=" * 80)
    print(f"Log directory:    {log_dir}")
    print(f"Strategy:         {cfg['STRATEGY_NAME']}")
    print(f"Hold-to-expiry:   {cfg.get('HOLD_TO_EXPIRY_DEFAULT', True) if cfg['STRATEGY_NAME'] != 'profit_1' else False}")
    print(f"Total bars:       {total_bars}")
    print(f"Trades entered:   {len(trades)}")

    if not trades:
        print("\nNo trades generated.")
        return

    # Time range
    first_ts = trades[0].ts
    last_ts = trades[-1].ts
    hours = (last_ts - first_ts) / 3600
    days = hours / 24

    print(f"Time span:        {hours:.1f} hours ({days:.1f} days)")
    print(f"First trade:      {datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Last trade:       {datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # PnL
    total_pnl = sum(t.pnl for t in trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0

    total_invested = sum(t.entry_price * t.shares for t in trades)
    roi = total_pnl / total_invested * 100 if total_invested > 0 else 0

    pnl_per_day = total_pnl / days if days > 0 else total_pnl
    trades_per_day = len(trades) / days if days > 0 else len(trades)

    print(f"\n{'─' * 40}")
    print(f"PERFORMANCE SUMMARY")
    print(f"{'─' * 40}")
    print(f"Total PnL:        ${total_pnl:+.2f}")
    print(f"PnL/day:          ${pnl_per_day:+.2f}")
    print(f"Trades/day:       {trades_per_day:.1f}")
    print(f"Win rate:         {wr:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"Total invested:   ${total_invested:.2f}")
    print(f"ROI:              {roi:+.1f}%")

    if wins:
        avg_win = sum(t.pnl for t in wins) / len(wins)
        print(f"Avg win:          ${avg_win:+.2f}")
    if losses:
        avg_loss = sum(t.pnl for t in losses) / len(losses)
        print(f"Avg loss:         ${avg_loss:+.2f}")

    # Exit reason breakdown
    exit_reasons = defaultdict(list)
    for t in trades:
        exit_reasons[t.exit_reason].append(t)

    print(f"\n{'─' * 40}")
    print("EXIT REASONS")
    print(f"{'─' * 40}")
    for reason, rtrades in sorted(exit_reasons.items(), key=lambda x: -len(x[1])):
        r_pnl = sum(t.pnl for t in rtrades)
        r_wins = len([t for t in rtrades if t.pnl > 0])
        r_wr = r_wins / len(rtrades) * 100 if rtrades else 0
        print(f"  {reason:20s}  n={len(rtrades):3d}  WR={r_wr:5.1f}%  PnL=${r_pnl:+7.2f}")

    # Direction breakdown
    print(f"\n{'─' * 40}")
    print("DIRECTION BREAKDOWN")
    print(f"{'─' * 40}")
    for d in ["UP", "DOWN"]:
        dt = [t for t in trades if t.direction == d]
        if dt:
            d_pnl = sum(t.pnl for t in dt)
            d_wins = len([t for t in dt if t.pnl > 0])
            d_wr = d_wins / len(dt) * 100
            print(f"  {d:5s}  n={len(dt):3d}  WR={d_wr:5.1f}%  PnL=${d_pnl:+7.2f}")

    # Price bucket analysis
    print(f"\n{'─' * 40}")
    print("ENTRY PRICE BUCKETS")
    print(f"{'─' * 40}")
    buckets = [(0, 0.15), (0.15, 0.25), (0.25, 0.35), (0.35, 0.50), (0.50, 0.65)]
    for lo, hi in buckets:
        bt = [t for t in trades if lo <= t.entry_price < hi]
        if bt:
            b_pnl = sum(t.pnl for t in bt)
            b_wins = len([t for t in bt if t.pnl > 0])
            b_wr = b_wins / len(bt) * 100
            print(f"  [{lo:.2f}-{hi:.2f})  n={len(bt):3d}  WR={b_wr:5.1f}%  PnL=${b_pnl:+7.2f}")

    # Config summary
    print(f"\n{'─' * 40}")
    print("KEY PARAMETERS")
    print(f"{'─' * 40}")
    params = [
        ("MIN_EDGE", f"{cfg['MIN_EDGE']:.4f}"),
        ("MIN_BTC_DISTANCE", f"{cfg['MIN_BTC_DISTANCE']:.5f}"),
        ("MIN_BOOK_DIVERGENCE", f"{cfg['MIN_BOOK_DIVERGENCE']:.4f}"),
        ("MIN_ENTRY_PRICE", f"{cfg['MIN_ENTRY_PRICE']:.2f}"),
        ("MAX_ENTRY_PRICE", f"{cfg['MAX_ENTRY_PRICE']:.2f}"),
        ("MAX_ENTRY_SPREAD", f"{cfg['MAX_ENTRY_SPREAD']:.3f}"),
        ("LATE_ENTRY_SECS", f"{cfg['LATE_ENTRY_SECS']}"),
        ("LATE_ENTRY_EDGE_DISCOUNT", f"{cfg['LATE_ENTRY_EDGE_DISCOUNT']:.2f}"),
        ("ENTRY_MIN_SECONDS_LEFT", f"{cfg['ENTRY_MIN_SECONDS_LEFT']}"),
        ("ENTRY_CONFIRMATION_TICKS", f"{cfg['ENTRY_CONFIRMATION_TICKS']}"),
        ("BET_SIZE_MIN/MAX", f"{cfg['BET_SIZE_MIN']:.2f}/{cfg['BET_SIZE_MAX']:.2f}"),
        ("MAX_BUDGET_FRACTION", f"{cfg['MAX_BUDGET_FRACTION']:.2f}"),
    ]
    if not (cfg.get("HOLD_TO_EXPIRY_DEFAULT", True) if cfg["STRATEGY_NAME"] != "profit_1" else False):
        params.extend([
            ("STOP_LOSS", f"{cfg['STOP_LOSS']:.3f}"),
            ("TAKE_PROFIT", f"{cfg['TAKE_PROFIT']:.3f}"),
            ("SIGNAL_EXIT_EDGE", f"{cfg['SIGNAL_EXIT_EDGE']:.3f}"),
            ("SL_ARM_DELAY_SECS", f"{cfg['SL_ARM_DELAY_SECS']}"),
        ])

    for name, val in params:
        print(f"  {name:30s} = {val}")

    # Individual trades
    print(f"\n{'─' * 40}")
    print("TRADE LOG")
    print(f"{'─' * 40}")
    print(f"{'Time':>19s}  {'Dir':>4s}  {'Entry':>5s}  {'Exit':>5s}  {'Shrs':>4s}  {'Edge':>6s}  {'PnL':>7s}  {'Reason':>15s}  {'Secs':>4s}  Question")
    for t in trades:
        ts_str = datetime.fromtimestamp(t.ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(
            f"{ts_str:>19s}  {t.direction:>4s}  {t.entry_price:5.3f}  {t.exit_price:5.3f}  {t.shares:4d}  "
            f"{t.edge:6.4f}  {t.pnl:+7.2f}  {t.exit_reason:>15s}  {t.seconds_left:4d}  "
            f"{t.question[:50]}"
        )

    print(f"\n{'=' * 80}")


if __name__ == "__main__":
    _backtest_cli_disabled()
