"""Walk-forward evaluation and simulation for PM BTC decision models."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from decision_features import ENTRY_FEATURE_COLUMNS, EXIT_FEATURE_COLUMNS
from prepare_decision_dataset import (
    build_bar_outcomes,
    bundle_name,
    clean_realized_metrics,
    compute_future_best_values,
    discover_bundle_dirs,
    load_bundle_rows,
)
from train_decision_models import train_grouped_classifier


@dataclass
class SimPosition:
    condition_id: str
    direction: str
    shares: int
    entry_price: float
    entry_ts: float
    entry_prob: float


@dataclass
class LoadedBundle:
    bundle_dir: str
    bundle: str
    all_rows: list[dict[str, Any]]
    outcomes: dict[str, int]
    historical_realized: dict[str, Any]


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "n_trades": 0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": None,
            "max_drawdown": 0.0,
            "exit_reason_split": {},
        }

    pnl_values = [float(trade["pnl"]) for trade in trades]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    gross_profit = sum(max(0.0, pnl) for pnl in pnl_values)
    gross_loss = -sum(min(0.0, pnl) for pnl in pnl_values)
    reasons = Counter(str(trade["exit_reason"]) for trade in trades)
    return {
        "n_trades": len(trades),
        "total_pnl": round(sum(pnl_values), 4),
        "avg_pnl": round(sum(pnl_values) / len(pnl_values), 4),
        "win_rate": round(sum(1 for pnl in pnl_values if pnl > 0) / len(pnl_values), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "max_drawdown": round(max_drawdown, 4),
        "exit_reason_split": dict(sorted(reasons.items())),
    }


def preload_bundle(bundle_dir: str) -> LoadedBundle:
    rows_by_bar = load_bundle_rows(bundle_dir)
    outcomes = build_bar_outcomes(rows_by_bar)
    all_rows: list[dict[str, Any]] = []
    for cid, rows in rows_by_bar.items():
        compute_future_best_values(rows, terminal_up_value=float(outcomes.get(cid, 0)))
        for row in rows:
            all_rows.append(dict(row))
    all_rows.sort(key=lambda row: float(row.get("ts") or 0.0))
    return LoadedBundle(
        bundle_dir=bundle_dir,
        bundle=bundle_name(bundle_dir),
        all_rows=all_rows,
        outcomes=outcomes,
        historical_realized=clean_realized_metrics(bundle_dir),
    )


def simulate_bundle(
    loaded: LoadedBundle,
    entry_model,
    exit_model,
    entry_threshold: float,
    exit_threshold: float,
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
            terminal_value = float(loaded.outcomes.get(position.condition_id, 0) if position.direction == "UP" else 1 - loaded.outcomes.get(position.condition_id, 0))
            close_position(exit_price=terminal_value, exit_ts=ts, exit_reason="bar_resolution")

        if position is None:
            if row.get("context") != "try_enter":
                continue
            from decision_features import extract_entry_features

            feats = extract_entry_features(row)
            if feats is None:
                continue
            score = float(entry_model.predict(np.array([[feats[col] for col in ENTRY_FEATURE_COLUMNS]]))[0])
            if score < entry_threshold:
                continue
            direction = "UP" if feats["direction_up"] >= 0.5 else "DOWN"
            shares = int(max(1.0, feats["signal_size"]))
            position = SimPosition(
                condition_id=cid,
                direction=direction,
                shares=shares,
                entry_price=float(feats["candidate_price"]),
                entry_ts=ts,
                entry_prob=score,
            )
            continue

        if row.get("context") != "manage_position":
            continue
        from decision_features import extract_exit_features

        feats = extract_exit_features(row)
        if feats is None:
            continue
        if feats["position_direction_up"] >= 0.5 and position.direction != "UP":
            continue
        if feats["position_direction_up"] < 0.5 and position.direction != "DOWN":
            continue
        score = float(exit_model.predict(np.array([[feats[col] for col in EXIT_FEATURE_COLUMNS]]))[0])
        if score < exit_threshold:
            continue
        close_position(exit_price=float(feats["current_side_bid"]), exit_ts=ts, exit_reason="exit_model")

    if position is not None:
        terminal_value = float(loaded.outcomes.get(position.condition_id, 0) if position.direction == "UP" else 1 - loaded.outcomes.get(position.condition_id, 0))
        last_ts = max(float(row.get("ts") or 0.0) for row in loaded.all_rows) if loaded.all_rows else 0.0
        close_position(exit_price=terminal_value, exit_ts=last_ts, exit_reason="bar_resolution")

    summary = summarize_trades(trades)
    summary["bundle"] = loaded.bundle
    summary["trades"] = trades
    summary["historical_realized"] = loaded.historical_realized
    return summary


def _fit_lightgbm(df: pd.DataFrame, feature_columns: list[str], label_col: str, group_col: str):
    model, _, _ = train_grouped_classifier(
        df=df,
        feature_columns=feature_columns,
        label_col=label_col,
        group_col=group_col,
        n_splits=min(5, max(2, df[group_col].nunique())),
        n_rounds=250,
    )
    return model


def find_best_thresholds(
    loaded_bundles: list[LoadedBundle],
    entry_model,
    exit_model,
) -> tuple[float, float]:
    entry_candidate_thresholds = [0.5, 0.55, 0.6, 0.65]
    exit_candidate_thresholds = [0.4, 0.45, 0.5, 0.55, 0.6]
    best_pair = (0.55, 0.55)
    best_score = float("-inf")

    for entry_threshold in entry_candidate_thresholds:
        for exit_threshold in exit_candidate_thresholds:
            total_pnl = 0.0
            total_trades = 0
            for loaded_bundle in loaded_bundles:
                result = simulate_bundle(loaded_bundle, entry_model, exit_model, entry_threshold, exit_threshold)
                total_pnl += float(result["total_pnl"])
                total_trades += int(result["n_trades"])
            score = total_pnl + 0.01 * total_trades
            if score > best_score:
                best_score = score
                best_pair = (entry_threshold, exit_threshold)
    return best_pair


def walk_forward(
    loaded_bundles: list[LoadedBundle],
    entry_df: pd.DataFrame,
    exit_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    ordered_bundles = [loaded.bundle for loaded in loaded_bundles]

    for idx in range(1, len(loaded_bundles)):
        train_bundles = ordered_bundles[:idx]
        train_entry_df = entry_df[entry_df["bundle"].isin(train_bundles)].copy()
        train_exit_df = exit_df[exit_df["bundle"].isin(train_bundles)].copy()
        if train_entry_df["entry_label"].nunique() < 2 or train_exit_df["exit_label"].nunique() < 2:
            continue
        if train_entry_df["condition_id"].nunique() < 2 or train_exit_df["trade_id"].nunique() < 2:
            continue

        entry_model = _fit_lightgbm(train_entry_df, ENTRY_FEATURE_COLUMNS, "entry_label", "condition_id")
        exit_model = _fit_lightgbm(train_exit_df, EXIT_FEATURE_COLUMNS, "exit_label", "trade_id")
        entry_threshold, exit_threshold = find_best_thresholds(loaded_bundles[:idx], entry_model, exit_model)
        bundle_result = simulate_bundle(loaded_bundles[idx], entry_model, exit_model, entry_threshold, exit_threshold)
        bundle_result["train_bundles"] = train_bundles
        bundle_result["entry_threshold"] = entry_threshold
        bundle_result["exit_threshold"] = exit_threshold
        results.append(bundle_result)

    return results


def aggregate_walk_forward(results: list[dict[str, Any]]) -> dict[str, Any]:
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
    parser.add_argument("--exit-dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--save-final-models-dir")
    args = parser.parse_args()

    bundle_dirs = discover_bundle_dirs(args.bundle_glob)
    if len(bundle_dirs) < 2:
        raise SystemExit("need at least two bundles for walk-forward evaluation")

    entry_df = pd.read_parquet(args.entry_dataset)
    exit_df = pd.read_parquet(args.exit_dataset)
    loaded_bundles = [preload_bundle(bundle_dir) for bundle_dir in bundle_dirs]
    results = walk_forward(loaded_bundles, entry_df, exit_df)
    aggregate = aggregate_walk_forward(results)

    output = {
        "walk_forward_results": results,
        "aggregate": aggregate,
    }

    if args.save_final_models_dir:
        os.makedirs(args.save_final_models_dir, exist_ok=True)
        final_entry = _fit_lightgbm(entry_df, ENTRY_FEATURE_COLUMNS, "entry_label", "condition_id")
        final_exit = _fit_lightgbm(exit_df, EXIT_FEATURE_COLUMNS, "exit_label", "trade_id")
        final_entry_threshold, final_exit_threshold = find_best_thresholds(loaded_bundles, final_entry, final_exit)
        final_entry.save_model(os.path.join(args.save_final_models_dir, "pm_btc_entry_gate_model.txt"))
        final_exit.save_model(os.path.join(args.save_final_models_dir, "pm_btc_exit_gate_model.txt"))
        output["final_model_thresholds"] = {
            "entry_threshold": final_entry_threshold,
            "exit_threshold": final_exit_threshold,
        }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as handle:
        json.dump(output, handle, indent=2)
    print(json.dumps(output["aggregate"], indent=2))
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
