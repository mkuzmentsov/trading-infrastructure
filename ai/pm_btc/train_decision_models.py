"""Train entry and exit decision models for PM BTC."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from decision_features import ENTRY_FEATURE_COLUMNS, EXIT_FEATURE_COLUMNS

try:
    import lightgbm as lgb
except ImportError as exc:
    raise SystemExit("lightgbm is required. Run `pip install -r requirements.txt` from ai/pm_btc/.") from exc

try:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.model_selection import GroupKFold
except ImportError as exc:
    raise SystemExit("scikit-learn is required. Run `pip install -r requirements.txt` from ai/pm_btc/.") from exc


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    clipped = np.clip(y_pred, 1e-6, 1 - 1e-6)
    unique = np.unique(y_true)
    return {
        "n": int(len(y_true)),
        "positives": int(np.sum(y_true)),
        "positive_rate": float(np.mean(y_true)),
        "auc": float(roc_auc_score(y_true, y_pred)) if len(unique) == 2 else None,
        "log_loss": float(log_loss(y_true, clipped)) if len(unique) == 2 else None,
        "brier": float(brier_score_loss(y_true, y_pred)),
        "mean_pred": float(np.mean(y_pred)),
    }


def train_grouped_classifier(
    df: pd.DataFrame,
    feature_columns: list[str],
    label_col: str,
    group_col: str,
    weight_col: str | None = "sample_weight",
    n_splits: int = 5,
    n_rounds: int = 300,
) -> tuple[lgb.Booster, dict[str, Any], np.ndarray]:
    X = df[feature_columns].fillna(0.0).values
    y = df[label_col].astype(int).values
    groups = df[group_col].astype(str).values
    weights = (
        df[weight_col].fillna(1.0).astype(float).values
        if weight_col and weight_col in df.columns
        else np.ones(len(df), dtype=float)
    )

    unique_groups = np.unique(groups)
    if len(unique_groups) < 2:
        raise ValueError(f"need at least 2 groups to train, got {len(unique_groups)}")

    n_splits = min(n_splits, len(unique_groups))
    if n_splits < 2:
        n_splits = 2

    oof_pred = np.zeros(len(df), dtype=float)
    fold_metrics: list[dict[str, Any]] = []
    best_iters: list[int] = []
    splitter = GroupKFold(n_splits=n_splits)

    pos = max(1, int(y.sum()))
    neg = max(1, int(len(y) - pos))
    scale_pos_weight = neg / pos

    for fold, (train_idx, val_idx) in enumerate(splitter.split(X, y, groups)):
        y_train = y[train_idx]
        dtrain = lgb.Dataset(X[train_idx], label=y_train, weight=weights[train_idx])
        dval = lgb.Dataset(X[val_idx], label=y[val_idx], weight=weights[val_idx], reference=dtrain)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.03,
            "num_leaves": 31,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 5,
            "min_data_in_leaf": max(20, min(100, len(train_idx) // 50)),
            "verbose": -1,
            "scale_pos_weight": scale_pos_weight,
        }
        booster = lgb.train(
            params,
            dtrain,
            num_boost_round=n_rounds,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
        )
        pred = booster.predict(X[val_idx], num_iteration=booster.best_iteration)
        oof_pred[val_idx] = pred
        fold_report = _metrics(y[val_idx], pred)
        fold_report["fold"] = fold
        fold_report["best_iter"] = int(booster.best_iteration or n_rounds)
        fold_metrics.append(fold_report)
        best_iters.append(int(booster.best_iteration or n_rounds))

    final_rounds = int(np.median(best_iters)) if best_iters else n_rounds
    full = lgb.Dataset(X, label=y, weight=weights)
    final = lgb.train(
        {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.03,
            "num_leaves": 31,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 5,
            "min_data_in_leaf": max(20, min(100, len(df) // 50)),
            "verbose": -1,
            "scale_pos_weight": scale_pos_weight,
        },
        full,
        num_boost_round=final_rounds,
    )

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(df)),
        "n_groups": int(len(unique_groups)),
        "label_col": label_col,
        "group_col": group_col,
        "weight_col": weight_col if weight_col in df.columns else None,
        "features": feature_columns,
        "oof_metrics": _metrics(y, oof_pred),
        "fold_metrics": fold_metrics,
        "final_rounds": final_rounds,
        "label_source_split": df["label_source"].value_counts().to_dict() if "label_source" in df.columns else {},
        "sample_weight_sum": float(weights.sum()),
        "feature_importance_gain": {
            name: float(score)
            for name, score in zip(feature_columns, final.feature_importance(importance_type="gain"))
        },
    }
    return final, report, oof_pred


def predict_dataframe(df: pd.DataFrame, model: lgb.Booster, feature_columns: list[str]) -> np.ndarray:
    X = df[feature_columns].fillna(0.0).values
    return model.predict(X)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-dataset", required=True)
    parser.add_argument("--exit-dataset", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=300)
    args = parser.parse_args()

    entry_df = pd.read_parquet(args.entry_dataset)
    exit_df = pd.read_parquet(args.exit_dataset)
    os.makedirs(args.output_dir, exist_ok=True)

    entry_model, entry_report, _ = train_grouped_classifier(
        entry_df,
        feature_columns=ENTRY_FEATURE_COLUMNS,
        label_col="entry_label",
        group_col="condition_id",
        n_splits=args.folds,
        n_rounds=args.rounds,
    )
    exit_model, exit_report, _ = train_grouped_classifier(
        exit_df,
        feature_columns=EXIT_FEATURE_COLUMNS,
        label_col="exit_label",
        group_col="trade_id",
        n_splits=args.folds,
        n_rounds=args.rounds,
    )

    entry_model_path = os.path.join(args.output_dir, "pm_btc_entry_gate_model.txt")
    exit_model_path = os.path.join(args.output_dir, "pm_btc_exit_gate_model.txt")
    entry_report_path = os.path.join(args.output_dir, "pm_btc_entry_gate_report.json")
    exit_report_path = os.path.join(args.output_dir, "pm_btc_exit_gate_report.json")

    entry_model.save_model(entry_model_path)
    exit_model.save_model(exit_model_path)
    with open(entry_report_path, "w") as handle:
        json.dump(entry_report, handle, indent=2)
    with open(exit_report_path, "w") as handle:
        json.dump(exit_report, handle, indent=2)

    print(f"saved {entry_model_path}")
    print(f"saved {exit_model_path}")
    print(f"saved {entry_report_path}")
    print(f"saved {exit_report_path}")


if __name__ == "__main__":
    main()
