"""Train LightGBM entry classifier with GroupKFold by condition_id.

Outputs:
  files/model/pm_btc_entry_smart_model.txt
  files/model/pm_btc_entry_smart_meta.json
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

from prepare_entry_dataset import FEATURE_COLUMNS

DEFAULT_DATA = "ai/pm_btc_entry/entry_dataset_v1.parquet"
DEFAULT_MODEL = "polymarket/k8s/helm/polymarket-btc-bot/files/model/pm_btc_entry_smart_model.txt"
DEFAULT_META = "polymarket/k8s/helm/polymarket-btc-bot/files/model/pm_btc_entry_smart_meta.json"


def evaluate_threshold(df: pd.DataFrame, oof: np.ndarray, thr: float) -> dict:
    keep = oof >= thr
    n_kept = int(keep.sum())
    n_total = len(df)
    if n_kept == 0:
        return {"thr": thr, "n_kept": 0, "kept_frac": 0.0,
                "kept_pnl": 0.0, "skipped_pnl": float(df["pnl"].sum()),
                "kept_winrate": None, "kept_avg_pnl": None}
    kept_pnl = float(df.loc[keep, "pnl"].sum())
    skipped_pnl = float(df.loc[~keep, "pnl"].sum())
    return {
        "thr": float(thr),
        "n_kept": n_kept,
        "kept_frac": n_kept / n_total,
        "kept_pnl": kept_pnl,
        "skipped_pnl": skipped_pnl,
        "kept_winrate": float(df.loc[keep, "label"].mean()),
        "kept_avg_pnl": kept_pnl / n_kept,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--model-out", default=DEFAULT_MODEL)
    ap.add_argument("--meta-out", default=DEFAULT_META)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--num-leaves", type=int, default=15)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-boost-round", type=int, default=400)
    ap.add_argument("--early-stop", type=int, default=30)
    ap.add_argument("--min-data-in-leaf", type=int, default=15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--repo-root", default=str(Path(__file__).resolve().parents[2]),
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve()
    df = pd.read_parquet(repo_root / args.data)
    print(f"loaded {len(df)} rows, {df['label'].mean():.3f} positive rate, "
          f"total pnl=${df['pnl'].sum():.2f}")

    X = df[FEATURE_COLUMNS].astype(float).values
    y = df["label"].astype(int).values
    groups = df["_cid"].astype(str).values
    n_groups = len(set(groups))
    print(f"n features={len(FEATURE_COLUMNS)}  n condition groups={n_groups}")

    folds = min(args.folds, n_groups)
    kf = GroupKFold(n_splits=folds)
    oof = np.zeros(len(df), dtype=float)
    fold_aucs, fold_briers, fold_iters = [], [], []

    for fold, (tr_idx, va_idx) in enumerate(kf.split(X, y, groups=groups)):
        dtr = lgb.Dataset(X[tr_idx], y[tr_idx], feature_name=FEATURE_COLUMNS)
        dva = lgb.Dataset(X[va_idx], y[va_idx], reference=dtr, feature_name=FEATURE_COLUMNS)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "num_leaves": args.num_leaves,
            "learning_rate": args.learning_rate,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 5,
            "min_data_in_leaf": args.min_data_in_leaf,
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
        auc = roc_auc_score(y[va_idx], pred) if len(set(y[va_idx])) > 1 else float("nan")
        brier = brier_score_loss(y[va_idx], pred)
        print(f"fold {fold}: best_iter={booster.best_iteration}  "
              f"AUC={auc:.4f}  Brier={brier:.4f}  "
              f"n_train={len(tr_idx)} n_val={len(va_idx)}")
        fold_aucs.append(auc)
        fold_briers.append(brier)
        fold_iters.append(booster.best_iteration)

    overall_auc = roc_auc_score(y, oof)
    overall_brier = brier_score_loss(y, oof)
    print(f"\nOOF: AUC={overall_auc:.4f}  Brier={overall_brier:.4f}")
    print(f"per-fold AUC: {[round(a,3) for a in fold_aucs]}  "
          f"mean={np.nanmean(fold_aucs):.3f}  std={np.nanstd(fold_aucs):.3f}")

    # Threshold sweep on OOF preds
    print("\nOOF threshold sweep:")
    print(f"{'thr':>5} {'kept':>5} {'frac':>5} {'WR':>5} {'kept_pnl':>9} {'skip_pnl':>9} {'avg':>6}")
    sweeps = []
    for thr in [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        s = evaluate_threshold(df, oof, thr)
        sweeps.append(s)
        wr = s["kept_winrate"] if s["kept_winrate"] is not None else float("nan")
        avg = s["kept_avg_pnl"] if s["kept_avg_pnl"] is not None else float("nan")
        print(f"{s['thr']:>5.2f} {s['n_kept']:>5d} {s['kept_frac']:>5.2f} "
              f"{wr:>5.2f} {s['kept_pnl']:>9.2f} {s['skipped_pnl']:>9.2f} {avg:>6.2f}")

    # Final fit on all data, anchor to median best_iter
    median_iter = int(np.median(fold_iters)) if fold_iters else args.num_boost_round // 2
    final_dtrain = lgb.Dataset(X, y, feature_name=FEATURE_COLUMNS)
    final_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "num_leaves": args.num_leaves,
        "learning_rate": args.learning_rate,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "min_data_in_leaf": args.min_data_in_leaf,
        "verbose": -1,
        "seed": args.seed,
    }
    final_booster = lgb.train(
        final_params, final_dtrain,
        num_boost_round=median_iter,
        callbacks=[lgb.log_evaluation(0)],
    )

    model_path = repo_root / args.model_out
    meta_path = repo_root / args.meta_out
    model_path.parent.mkdir(parents=True, exist_ok=True)
    final_booster.save_model(str(model_path))

    importance = final_booster.feature_importance(importance_type="gain")
    fi = sorted(zip(FEATURE_COLUMNS, importance), key=lambda x: -x[1])

    meta = {
        "version": "entry_smart_v1",
        "n_rows": int(len(df)),
        "n_groups": int(n_groups),
        "feature_columns": FEATURE_COLUMNS,
        "label_definition": "1 iff close pnl > 0",
        "oof_auc": float(overall_auc),
        "oof_brier": float(overall_brier),
        "fold_aucs": [float(a) for a in fold_aucs],
        "fold_briers": [float(b) for b in fold_briers],
        "fold_iters": [int(i) for i in fold_iters],
        "params": final_params,
        "num_boost_round_final": int(median_iter),
        "feature_importance_gain": [
            {"feature": f, "gain": float(g)} for f, g in fi
        ],
        "threshold_sweep_oof": sweeps,
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nwrote {model_path}")
    print(f"wrote {meta_path}")
    print("\nTop 15 features by gain:")
    for f, g in fi[:15]:
        print(f"  {g:>10.1f}  {f}")


if __name__ == "__main__":
    main()
