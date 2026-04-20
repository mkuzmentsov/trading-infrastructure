"""v2 trainer for the PM BTC entry gate.

Improvements vs train_decision_models.py:
  * Purged walk-forward CV (groups ordered chronologically, embargo between
    train and val).
  * LightGBM monotone_constraints for features where the sign is known.
  * Stronger regularization (lambda_l2, min_gain_to_split), no
    scale_pos_weight so predicted probabilities remain calibrated.
  * Post-training isotonic calibration fit on the concatenated OOF
    predictions and serialized to JSON alongside the booster.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from decision_features_v2 import (
    ENTRY_FEATURE_COLUMNS_V2,
    monotone_constraints_for,
)

try:
    import lightgbm as lgb
except ImportError as exc:
    raise SystemExit("lightgbm is required — pip install -r requirements.txt") from exc

try:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
except ImportError as exc:
    raise SystemExit("scikit-learn is required — pip install -r requirements.txt") from exc


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    clipped = np.clip(y_pred, 1e-6, 1 - 1e-6)
    unique = np.unique(y_true)
    return {
        "n": int(len(y_true)),
        "positives": int(np.sum(y_true)),
        "positive_rate": float(np.mean(y_true)) if len(y_true) else 0.0,
        "auc": float(roc_auc_score(y_true, y_pred)) if len(unique) == 2 else None,
        "log_loss": float(log_loss(y_true, clipped)) if len(unique) == 2 else None,
        "brier": float(brier_score_loss(y_true, y_pred)) if len(y_true) else 0.0,
        "mean_pred": float(np.mean(y_pred)) if len(y_pred) else 0.0,
    }


def build_walk_forward_splits(
    group_values: np.ndarray,
    bundle_order: list[str],
    min_train_bundles: int = 2,
    embargo_bundles: int = 0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Chronological walk-forward: for each bundle past the warm-up, train on
    everything strictly before (minus embargo) and validate on that bundle."""
    idx_by_bundle = {b: np.where(group_values == b)[0] for b in bundle_order}
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for i, bundle in enumerate(bundle_order):
        if i < min_train_bundles:
            continue
        train_bundles = bundle_order[: max(0, i - embargo_bundles)]
        if not train_bundles:
            continue
        train_idx = np.concatenate([idx_by_bundle[b] for b in train_bundles if len(idx_by_bundle[b])])
        val_idx = idx_by_bundle[bundle]
        if len(train_idx) == 0 or len(val_idx) == 0:
            continue
        splits.append((train_idx, val_idx))
    return splits


def train_entry_gate_v2(
    df: pd.DataFrame,
    bundle_order: list[str],
    primary_label: str,
    feature_columns: list[str],
    n_rounds: int = 400,
    embargo_bundles: int = 0,
    min_train_bundles: int = 2,
) -> tuple[lgb.Booster, IsotonicRegression, dict[str, Any]]:
    X = df[feature_columns].fillna(0.0).values
    y = df[primary_label].astype(int).values
    groups = df["bundle"].astype(str).values

    monotone = monotone_constraints_for(feature_columns)
    monotone_str = ",".join(str(v) for v in monotone)

    base_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.03,
        "num_leaves": 31,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "min_data_in_leaf": max(20, min(100, len(df) // 50)),
        "lambda_l2": 1.0,
        "min_gain_to_split": 0.0,
        "verbose": -1,
        "monotone_constraints": monotone_str,
        "monotone_constraints_method": "advanced",
    }

    splits = build_walk_forward_splits(
        group_values=groups,
        bundle_order=bundle_order,
        min_train_bundles=min_train_bundles,
        embargo_bundles=embargo_bundles,
    )
    if not splits:
        raise SystemExit(
            f"need at least {min_train_bundles + 1} bundles to walk-forward; "
            f"got {len(bundle_order)}"
        )

    oof_true: list[int] = []
    oof_pred: list[float] = []
    oof_bundle: list[str] = []
    fold_reports: list[dict[str, Any]] = []
    best_iters: list[int] = []

    for i, (train_idx, val_idx) in enumerate(splits):
        val_bundle = groups[val_idx][0] if len(val_idx) else "?"
        dtrain = lgb.Dataset(X[train_idx], label=y[train_idx])
        dval = lgb.Dataset(X[val_idx], label=y[val_idx], reference=dtrain)
        booster = lgb.train(
            base_params,
            dtrain,
            num_boost_round=n_rounds,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
        )
        iters = int(booster.best_iteration or n_rounds)
        best_iters.append(iters)

        pred = booster.predict(X[val_idx], num_iteration=iters)
        oof_true.extend(y[val_idx].tolist())
        oof_pred.extend(pred.tolist())
        oof_bundle.extend(groups[val_idx].tolist())

        report = _metrics(y[val_idx], pred)
        report["fold"] = i
        report["val_bundle"] = val_bundle
        report["best_iter"] = iters
        fold_reports.append(report)
        auc_str = f"{report['auc']:.4f}" if report["auc"] is not None else "n/a"
        logloss_str = f"{report['log_loss']:.4f}" if report["log_loss"] is not None else "n/a"
        print(
            f"fold {i}: bundle={val_bundle} "
            f"auc={auc_str} log_loss={logloss_str} "
            f"n_val={report['n']} best_iter={iters}"
        )

    oof_true_arr = np.asarray(oof_true, dtype=int)
    oof_pred_arr = np.asarray(oof_pred, dtype=float)
    overall = _metrics(oof_true_arr, oof_pred_arr)

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(oof_pred_arr, oof_true_arr)
    cal_pred = calibrator.predict(oof_pred_arr)
    cal_overall = _metrics(oof_true_arr, cal_pred)

    median_iter = int(np.median(best_iters)) if best_iters else n_rounds
    full = lgb.Dataset(X, label=y)
    final = lgb.train(base_params, full, num_boost_round=median_iter)

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(df)),
        "n_bundles": int(df["bundle"].nunique()),
        "primary_label": primary_label,
        "features": feature_columns,
        "monotone_constraints": {name: monotone[i] for i, name in enumerate(feature_columns) if monotone[i] != 0},
        "walk_forward_folds": fold_reports,
        "oof_raw_metrics": overall,
        "oof_calibrated_metrics": cal_overall,
        "final_rounds": median_iter,
        "feature_importance_gain": {
            name: float(score)
            for name, score in zip(feature_columns, final.feature_importance(importance_type="gain"))
        },
        "isotonic": {
            "x_thresholds": [float(x) for x in getattr(calibrator, "X_thresholds_", [])],
            "y_thresholds": [float(y_) for y_ in getattr(calibrator, "y_thresholds_", [])],
            "out_of_bounds": calibrator.out_of_bounds,
            "increasing": bool(getattr(calibrator, "increasing_", True)),
        },
    }
    return final, calibrator, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--bundle-order", required=True,
                        help="Path to pm_btc_bundle_order_v2.json from prepare_decision_dataset_v2.py")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--primary-label", default="label_60s")
    parser.add_argument("--rounds", type=int, default=400)
    parser.add_argument("--embargo-bundles", type=int, default=0)
    parser.add_argument("--min-train-bundles", type=int, default=2)
    args = parser.parse_args()

    df = pd.read_parquet(args.dataset)
    with open(args.bundle_order) as handle:
        bundle_records = json.load(handle)
    bundle_order = [rec["bundle"] for rec in bundle_records]
    # Keep only bundles that actually contributed rows.
    bundle_order = [b for b in bundle_order if b in set(df["bundle"].unique())]
    print(f"dataset rows={len(df)} bundles={len(bundle_order)} primary_label={args.primary_label}")

    os.makedirs(args.output_dir, exist_ok=True)
    model, calibrator, report = train_entry_gate_v2(
        df=df,
        bundle_order=bundle_order,
        primary_label=args.primary_label,
        feature_columns=ENTRY_FEATURE_COLUMNS_V2,
        n_rounds=args.rounds,
        embargo_bundles=args.embargo_bundles,
        min_train_bundles=args.min_train_bundles,
    )

    model_path = os.path.join(args.output_dir, "pm_btc_entry_gate_model_v2.txt")
    calibrator_path = os.path.join(args.output_dir, "pm_btc_entry_gate_calibrator_v2.json")
    report_path = os.path.join(args.output_dir, "pm_btc_entry_gate_report_v2.json")

    model.save_model(model_path)
    with open(calibrator_path, "w") as handle:
        json.dump(report["isotonic"], handle, indent=2)
    with open(report_path, "w") as handle:
        json.dump(report, handle, indent=2)

    print(f"saved {model_path}")
    print(f"saved {calibrator_path}")
    print(f"saved {report_path}")
    print()
    print("OOF raw:       ", report["oof_raw_metrics"])
    print("OOF calibrated:", report["oof_calibrated_metrics"])


if __name__ == "__main__":
    main()
