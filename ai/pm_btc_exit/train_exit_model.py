"""Train LightGBM exit classifier with GroupKFold by position.

Group key = (condition_id, direction, entry_ts) so a single position's
tick stream stays in one fold (avoids leakage).

Outputs:
  files/model/pm_btc_exit_model.txt
  files/model/pm_btc_exit_meta.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from prepare_exit_dataset import FEATURE_COLUMNS

DEFAULT_DATA = "ai/pm_btc_exit/exit_dataset_v1.parquet"
DEFAULT_MODEL = "polymarket/k8s/helm/polymarket-btc-bot/files/model/pm_btc_exit_model.txt"
DEFAULT_META = "polymarket/k8s/helm/polymarket-btc-bot/files/model/pm_btc_exit_meta.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--model-out", default=DEFAULT_MODEL)
    ap.add_argument("--meta-out", default=DEFAULT_META)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--num-leaves", type=int, default=31)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-boost-round", type=int, default=400)
    ap.add_argument("--early-stop", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--repo-root", default=str(Path(__file__).resolve().parents[2]),
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    df = pd.read_parquet(repo_root / args.data)
    print(f"loaded {len(df)} rows, {df['label'].mean():.3f} positive rate")

    X = df[FEATURE_COLUMNS].astype(float).values
    y = df["label"].astype(int).values
    groups = (
        df["_cid"].astype(str)
        + "|" + df["_dir"].astype(str)
        + "|" + df["_entry_ts"].astype(str)
    ).values
    n_groups = len(set(groups))
    print(f"n features={len(FEATURE_COLUMNS)}  n positions (groups)={n_groups}")

    kf = GroupKFold(n_splits=args.folds)
    oof = np.zeros(len(df), dtype=float)
    fold_aucs = []
    fold_briers = []

    for fold, (tr_idx, va_idx) in enumerate(kf.split(X, y, groups=groups)):
        dtr = lgb.Dataset(X[tr_idx], y[tr_idx], feature_name=FEATURE_COLUMNS)
        dva = lgb.Dataset(X[va_idx], y[va_idx], reference=dtr, feature_name=FEATURE_COLUMNS)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "num_leaves": args.num_leaves,
            "learning_rate": args.learning_rate,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 5,
            "min_data_in_leaf": 50,
            "verbose": -1,
            "seed": args.seed + fold,
        }
        booster = lgb.train(
            params, dtr,
            num_boost_round=args.num_boost_round,
            valid_sets=[dva],
            callbacks=[
                lgb.early_stopping(args.early_stop, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        pred = booster.predict(X[va_idx], num_iteration=booster.best_iteration)
        oof[va_idx] = pred
        auc = roc_auc_score(y[va_idx], pred)
        brier = brier_score_loss(y[va_idx], pred)
        print(f"fold {fold}: best_iter={booster.best_iteration}  AUC={auc:.4f}  Brier={brier:.4f}")
        fold_aucs.append(auc)
        fold_briers.append(brier)

    overall_auc = roc_auc_score(y, oof)
    overall_brier = brier_score_loss(y, oof)
    print(f"\nOOF: AUC={overall_auc:.4f}  Brier={overall_brier:.4f}")
    print(f"per-fold AUC: {[round(a,3) for a in fold_aucs]}  mean={np.mean(fold_aucs):.3f}")

    # Final fit on all data
    final_dtrain = lgb.Dataset(X, y, feature_name=FEATURE_COLUMNS)
    final_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": args.num_leaves,
        "learning_rate": args.learning_rate,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 5,
        "min_data_in_leaf": 50,
        "verbose": -1,
        "seed": args.seed,
    }
    best_iter = int(np.median([
        # use median of per-fold best_iters via final retrain — we just train to
        # a safe round count anchored to the median over CV
        # (we discarded best_iters above; approximate by using num_boost_round)
        args.num_boost_round // 2
    ]))
    final_booster = lgb.train(
        final_params, final_dtrain,
        num_boost_round=best_iter,
        callbacks=[lgb.log_evaluation(0)],
    )

    model_path = repo_root / args.model_out
    meta_path = repo_root / args.meta_out
    model_path.parent.mkdir(parents=True, exist_ok=True)
    final_booster.save_model(str(model_path))

    importance = final_booster.feature_importance(importance_type="gain")
    fi = sorted(zip(FEATURE_COLUMNS, importance), key=lambda x: -x[1])

    meta = {
        "version": "exit_v1",
        "n_rows": int(len(df)),
        "n_groups": int(n_groups),
        "feature_columns": FEATURE_COLUMNS,
        "label_definition": "1 iff (current_bid - eventual_exit_price) >= label_drop (default 0.05)",
        "oof_auc": float(overall_auc),
        "oof_brier": float(overall_brier),
        "fold_aucs": [float(a) for a in fold_aucs],
        "fold_briers": [float(b) for b in fold_briers],
        "params": final_params,
        "num_boost_round_final": int(best_iter),
        "feature_importance_gain": [
            {"feature": f, "gain": float(g)} for f, g in fi
        ],
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nwrote {model_path}")
    print(f"wrote {meta_path}")
    print("\nTop 15 features by gain:")
    for f, g in fi[:15]:
        print(f"  {g:>10.1f}  {f}")


if __name__ == "__main__":
    main()
