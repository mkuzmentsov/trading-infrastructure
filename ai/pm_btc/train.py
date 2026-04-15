"""Train a LightGBM classifier that predicts P(bar resolves UP) from a
mid-bar snapshot. Splits are grouped by condition_id so within-bar leakage is
impossible.

Usage:
    python train.py \\
        --dataset outputs/pm_btc_dataset.parquet \\
        --output outputs/pm_btc_model.txt \\
        --report outputs/pm_btc_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from features import FEATURE_COLUMNS  # noqa: E402

try:
    import lightgbm as lgb
except ImportError as e:
    raise SystemExit(
        "lightgbm is not installed. Run `pip install -r requirements.txt` "
        "from ai/pm_btc/ first."
    ) from e

try:
    from sklearn.calibration import CalibratedClassifierCV  # noqa: F401
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.model_selection import GroupKFold
except ImportError as e:
    raise SystemExit(
        "scikit-learn is not installed. Run `pip install -r requirements.txt` "
        "from ai/pm_btc/ first."
    ) from e


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "n": int(len(y_true)),
        "auc": float(roc_auc_score(y_true, y_pred)) if len(np.unique(y_true)) == 2 else None,
        "log_loss": float(log_loss(y_true, np.clip(y_pred, 1e-6, 1 - 1e-6))),
        "brier": float(brier_score_loss(y_true, y_pred)),
        "mean_pred": float(np.mean(y_pred)),
        "mean_label": float(np.mean(y_true)),
    }


def _reliability_buckets(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Group predictions into probability bins, report observed frequency per
    bin. If model is well-calibrated, predicted ≈ observed in every bucket."""
    out = []
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (y_pred >= lo) & (y_pred < hi if hi < 1.0 else y_pred <= hi)
        if not mask.any():
            continue
        out.append({
            "range": [float(lo), float(hi)],
            "n": int(mask.sum()),
            "mean_pred": float(y_pred[mask].mean()),
            "observed_up_rate": float(y_true[mask].mean()),
        })
    return out


def train(df: pd.DataFrame, n_splits: int = 5, n_rounds: int = 400) -> tuple:
    """Train with GroupKFold CV. Returns (final_model, cv_report)."""
    X = df[FEATURE_COLUMNS].values
    y = df["y"].values.astype(int)
    groups = df["condition_id"].values

    n_groups = len(np.unique(groups))
    if n_groups < n_splits:
        n_splits = max(2, n_groups - 1)
        print(f"only {n_groups} unique bars — using n_splits={n_splits}")

    oof_pred = np.zeros(len(y), dtype=float)
    fold_metrics = []
    gkf = GroupKFold(n_splits=n_splits)
    for fold, (train_idx, val_idx) in enumerate(gkf.split(X, y, groups)):
        dtrain = lgb.Dataset(X[train_idx], label=y[train_idx])
        dval = lgb.Dataset(X[val_idx], label=y[val_idx], reference=dtrain)
        params = dict(
            objective="binary",
            metric="binary_logloss",
            learning_rate=0.03,
            num_leaves=31,
            feature_fraction=0.8,
            bagging_fraction=0.8,
            bagging_freq=5,
            min_data_in_leaf=50,
            verbose=-1,
        )
        booster = lgb.train(
            params,
            dtrain,
            num_boost_round=n_rounds,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
        )
        oof_pred[val_idx] = booster.predict(X[val_idx], num_iteration=booster.best_iteration)
        m = _metrics(y[val_idx], oof_pred[val_idx])
        m["fold"] = fold
        m["best_iter"] = int(booster.best_iteration or n_rounds)
        fold_metrics.append(m)
        print(f"fold {fold}: auc={m['auc']} log_loss={m['log_loss']:.4f} n={m['n']}")

    overall = _metrics(y, oof_pred)
    reliability = _reliability_buckets(y, oof_pred, n_bins=10)

    print("\n--- OOF metrics ---")
    print(json.dumps(overall, indent=2))
    print("\n--- reliability (calibration) ---")
    for b in reliability:
        print(f"  {b['range'][0]:.2f}-{b['range'][1]:.2f}  "
              f"n={b['n']:4d}  pred={b['mean_pred']:.3f}  observed={b['observed_up_rate']:.3f}")

    # Final model: retrain on all data with the median best_iter across folds.
    best_iters = [fm["best_iter"] for fm in fold_metrics]
    final_rounds = int(np.median(best_iters))
    print(f"\nretraining final model on all data for {final_rounds} rounds")
    full = lgb.Dataset(X, label=y)
    final_params = dict(
        objective="binary",
        metric="binary_logloss",
        learning_rate=0.03,
        num_leaves=31,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        min_data_in_leaf=50,
        verbose=-1,
    )
    final = lgb.train(final_params, full, num_boost_round=final_rounds)

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(df)),
        "n_bars": int(df["condition_id"].nunique()),
        "features": FEATURE_COLUMNS,
        "fold_metrics": fold_metrics,
        "oof_overall": overall,
        "reliability": reliability,
        "final_rounds": final_rounds,
        "feature_importance": dict(zip(
            FEATURE_COLUMNS,
            [int(v) for v in final.feature_importance(importance_type="gain")],
        )),
    }
    return final, report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=400)
    args = ap.parse_args()

    df = pd.read_parquet(args.dataset)
    print(f"loaded {len(df)} rows / {df['condition_id'].nunique()} bars "
          f"from {args.dataset}")

    model, report = train(df, n_splits=args.folds, n_rounds=args.rounds)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    model.save_model(args.output)
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nmodel saved: {args.output}\nreport saved: {args.report}")


if __name__ == "__main__":
    main()
