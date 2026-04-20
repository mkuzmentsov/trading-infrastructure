"""Walk-forward simulation for ML entry + deterministic exit rules."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from decision_features import ENTRY_FEATURE_COLUMNS, extract_entry_features, extract_exit_features
from prepare_decision_dataset import discover_bundle_dirs
from simulate_decision_strategy import LoadedBundle, preload_bundle, summarize_trades
from train_decision_models import train_grouped_classifier


@dataclass
class SimPosition:
    condition_id: str
    direction: str
    shares: int
    entry_price: float
    entry_ts: float
    entry_prob: float
    entry_edge: float
    entry_seconds_left: int
    peak_bid: float
    trailing_armed: bool = False
    allow_hold_to_expiry: bool = False


RULES = {
    "min_entry_price": 0.35,
    "cheap_override_score": 0.75,
    "cheap_override_edge": 0.20,
    "base_stop_loss": 0.10,
    "late_stop_loss": 0.08,
    "late_stop_secs": 90,
    "trailing_arm_gain": 0.08,
    "trailing_gap": 0.05,
    "thesis_profit_lock": 0.04,
    "thesis_floor_min": 0.02,
    "thesis_entry_fraction": 0.35,
    "late_bar_cut_secs": 45,
    "late_bar_cut_positive_secs": 25,
    "late_bar_positive_floor": 0.03,
    "dominant_edge_floor": 0.08,
    "dominant_entry_fraction": 0.5,
    "force_exit_secs": 10,
    "hold_score_min": 0.70,
    "hold_price_max": 0.35,
    "hold_seconds_left_max": 150,
}


def _fit_entry_model(entry_df: pd.DataFrame):
    model, _, _ = train_grouped_classifier(
        df=entry_df,
        feature_columns=ENTRY_FEATURE_COLUMNS,
        label_col="entry_label",
        group_col="condition_id",
        n_splits=min(5, max(2, entry_df["condition_id"].nunique())),
        n_rounds=250,
    )
    return model


def _entry_score(entry_model, feats: dict[str, float]) -> float:
    row = np.array([[feats[col] for col in ENTRY_FEATURE_COLUMNS]])
    return float(entry_model.predict(row)[0])


def _entry_allowed(feats: dict[str, float], score: float, rules: dict[str, float]) -> bool:
    price = float(feats["candidate_price"])
    side_edge = float(feats["signal_side_edge"])
    if price >= rules["min_entry_price"]:
        return True
    return score >= rules["cheap_override_score"] and side_edge >= rules["cheap_override_edge"]


def _should_exit(pos: SimPosition, feats: dict[str, float]) -> tuple[bool, str]:
    seconds_left = int(feats["seconds_left"])
    current_bid = float(feats["current_side_bid"])
    signal_side_edge = float(feats["signal_side_edge"])
    unrealized = float(feats["current_unrealized"])
    pos.peak_bid = max(pos.peak_bid, current_bid)

    stop_gap = RULES["late_stop_loss"] if seconds_left <= RULES["late_stop_secs"] else RULES["base_stop_loss"]
    if current_bid <= pos.entry_price - stop_gap:
        return True, "stop_loss"

    if current_bid >= pos.entry_price + RULES["trailing_arm_gain"]:
        pos.trailing_armed = True
    if pos.trailing_armed and current_bid <= pos.peak_bid - RULES["trailing_gap"]:
        return True, "trailing_stop"

    thesis_floor = max(RULES["thesis_floor_min"], RULES["thesis_entry_fraction"] * pos.entry_edge)
    if unrealized >= RULES["thesis_profit_lock"] and signal_side_edge < thesis_floor:
        return True, "thesis_decay"

    if seconds_left <= RULES["late_bar_cut_secs"] and unrealized < 0:
        return True, "late_bar_cut"

    dominant_edge_floor = max(RULES["dominant_edge_floor"], RULES["dominant_entry_fraction"] * pos.entry_edge)
    clearly_dominant = signal_side_edge >= dominant_edge_floor
    if (
        seconds_left <= RULES["late_bar_cut_positive_secs"]
        and unrealized < RULES["late_bar_positive_floor"]
        and not clearly_dominant
        and not pos.allow_hold_to_expiry
    ):
        return True, "late_bar_fade"

    if seconds_left <= RULES["force_exit_secs"] and not pos.allow_hold_to_expiry:
        return True, "force_close"

    return False, ""


def simulate_bundle_rule_exit(
    loaded: LoadedBundle,
    entry_model,
    entry_threshold: float,
    rules: dict[str, float],
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    position: SimPosition | None = None

    def close_position(exit_price: float, exit_ts: float, exit_reason: str) -> None:
        nonlocal position
        if position is None:
            return
        pnl = (exit_price - position.entry_price) * position.shares
        trades.append(
            {
                "bundle": loaded.bundle,
                "condition_id": position.condition_id,
                "direction": position.direction,
                "shares": position.shares,
                "entry_price": round(position.entry_price, 4),
                "exit_price": round(exit_price, 4),
                "entry_ts": position.entry_ts,
                "exit_ts": exit_ts,
                "entry_prob": round(position.entry_prob, 6),
                "pnl": round(pnl, 4),
                "exit_reason": exit_reason,
            }
        )
        position = None

    for row in loaded.all_rows:
        cid = str(row.get("condition_id"))
        ts = float(row.get("ts") or 0.0)

        if position is not None and cid != position.condition_id:
            terminal_value = float(
                loaded.outcomes.get(position.condition_id, 0)
                if position.direction == "UP"
                else 1 - loaded.outcomes.get(position.condition_id, 0)
            )
            close_position(exit_price=terminal_value, exit_ts=ts, exit_reason="bar_resolution")

        if position is None:
            if row.get("context") != "try_enter":
                continue
            feats = extract_entry_features(row)
            if feats is None:
                continue
            score = _entry_score(entry_model, feats)
            if score < entry_threshold:
                continue
            if not _entry_allowed(feats, score, rules):
                continue
            direction = "UP" if feats["direction_up"] >= 0.5 else "DOWN"
            entry_price = float(feats["candidate_price"])
            entry_seconds_left = int(feats["seconds_left"])
            allow_hold = (
                score >= RULES["hold_score_min"]
                and entry_price <= RULES["hold_price_max"]
                and entry_seconds_left <= RULES["hold_seconds_left_max"]
            )
            position = SimPosition(
                condition_id=cid,
                direction=direction,
                shares=int(max(1.0, feats["signal_size"])),
                entry_price=entry_price,
                entry_ts=ts,
                entry_prob=score,
                entry_edge=float(feats["signal_side_edge"]),
                entry_seconds_left=entry_seconds_left,
                peak_bid=float(feats["candidate_bid"]),
                allow_hold_to_expiry=allow_hold,
            )
            continue

        if row.get("context") != "manage_position":
            continue
        feats = extract_exit_features(row)
        if feats is None:
            continue
        if feats["position_direction_up"] >= 0.5 and position.direction != "UP":
            continue
        if feats["position_direction_up"] < 0.5 and position.direction != "DOWN":
            continue

        should_exit, reason = _should_exit(position, feats)
        if should_exit:
            close_position(exit_price=float(feats["current_side_bid"]), exit_ts=ts, exit_reason=reason)

    if position is not None:
        terminal_value = float(
            loaded.outcomes.get(position.condition_id, 0)
            if position.direction == "UP"
            else 1 - loaded.outcomes.get(position.condition_id, 0)
        )
        last_ts = max(float(row.get("ts") or 0.0) for row in loaded.all_rows) if loaded.all_rows else 0.0
        close_position(exit_price=terminal_value, exit_ts=last_ts, exit_reason="bar_resolution")

    summary = summarize_trades(trades)
    summary["bundle"] = loaded.bundle
    summary["trades"] = trades
    summary["historical_realized"] = loaded.historical_realized
    return summary


def find_best_entry_threshold(loaded_bundles: list[LoadedBundle], entry_model) -> tuple[float, dict[str, float]]:
    best_threshold = 0.60
    best_rules = dict(RULES)
    best_score = float("-inf")
    for threshold in [0.55, 0.60, 0.65, 0.70]:
        for min_entry_price in [0.25, 0.30, 0.35]:
            for cheap_override_score in [0.72, 0.75, 0.78]:
                rules = dict(RULES)
                rules["min_entry_price"] = min_entry_price
                rules["cheap_override_score"] = cheap_override_score
                total_pnl = 0.0
                total_trades = 0
                for loaded in loaded_bundles:
                    result = simulate_bundle_rule_exit(loaded, entry_model, threshold, rules)
                    total_pnl += float(result["total_pnl"])
                    total_trades += int(result["n_trades"])
                score = total_pnl + 0.01 * total_trades
                if score > best_score:
                    best_score = score
                    best_threshold = threshold
                    best_rules = rules
    return best_threshold, best_rules


def walk_forward_rule_exit(loaded_bundles: list[LoadedBundle], entry_df: pd.DataFrame) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    ordered_bundles = [loaded.bundle for loaded in loaded_bundles]

    for idx in range(1, len(loaded_bundles)):
        train_bundles = ordered_bundles[:idx]
        train_entry_df = entry_df[entry_df["bundle"].isin(train_bundles)].copy()
        if train_entry_df["entry_label"].nunique() < 2 or train_entry_df["condition_id"].nunique() < 2:
            continue
        entry_model = _fit_entry_model(train_entry_df)
        entry_threshold, rules = find_best_entry_threshold(loaded_bundles[:idx], entry_model)
        bundle_result = simulate_bundle_rule_exit(loaded_bundles[idx], entry_model, entry_threshold, rules)
        bundle_result["train_bundles"] = train_bundles
        bundle_result["entry_threshold"] = entry_threshold
        bundle_result["rules"] = rules
        results.append(bundle_result)

    return results


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    realized_pnl = 0.0
    realized_closes = 0
    for result in results:
        trades.extend(result.get("trades", []))
        hist = result.get("historical_realized", {})
        realized_pnl += float(hist.get("realized_pnl") or 0.0)
        realized_closes += int(hist.get("n_clean_closes") or 0)
    summary = summarize_trades(trades)
    summary["walk_forward_bundles"] = [result["bundle"] for result in results]
    summary["historical_realized_total_pnl"] = round(realized_pnl, 4)
    summary["historical_realized_clean_closes"] = realized_closes
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-glob", action="append", required=True)
    parser.add_argument("--entry-dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--save-final-models-dir")
    args = parser.parse_args()

    bundle_dirs = discover_bundle_dirs(args.bundle_glob)
    if len(bundle_dirs) < 2:
        raise SystemExit("need at least two bundles for walk-forward evaluation")

    entry_df = pd.read_parquet(args.entry_dataset)
    loaded_bundles = [preload_bundle(bundle_dir) for bundle_dir in bundle_dirs]
    results = walk_forward_rule_exit(loaded_bundles, entry_df)
    aggregate = aggregate_results(results)
    output = {
        "rules": RULES,
        "walk_forward_results": results,
        "aggregate": aggregate,
    }

    if args.save_final_models_dir:
        os.makedirs(args.save_final_models_dir, exist_ok=True)
        final_entry = _fit_entry_model(entry_df)
        final_entry_threshold, final_rules = find_best_entry_threshold(loaded_bundles, final_entry)
        final_entry.save_model(os.path.join(args.save_final_models_dir, "pm_btc_entry_gate_model_rule_exit.txt"))
        output["final_model_thresholds"] = {"entry_threshold": final_entry_threshold}
        output["final_rules"] = final_rules

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as handle:
        json.dump(output, handle, indent=2)
    print(json.dumps(output["aggregate"], indent=2))
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
