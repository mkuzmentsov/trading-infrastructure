"""
Two-stage training for BTC 5m direction model.

Stage 1 — Pretrain: train on multiple assets (e.g. BTC + ETH) to learn
           general crypto market structure from more data.
Stage 2 — Fine-tune: continue training on BTC only to specialise.

Usage:
    python train_staged.py \
        --pretrain outputs/kraken/BTC/BTCUSD_features.csv \
                   outputs/kraken/ETH/ETHUSD_features.csv \
        --finetune outputs/kraken/BTC/BTCUSD_features.csv \
        --target   target_dir_1bar
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("train_staged")

RAW_COLS   = {"timestamp", "open", "high", "low", "close", "volume", "trades"}
TRAIN_FRAC = 0.70
VAL_FRAC   = 0.15

LGB_PARAMS = {
    "objective":              "binary",
    "metric":                 ["binary_logloss", "auc"],
    "boosting_type":          "gbdt",
    "learning_rate":          0.02,
    "num_leaves":             127,
    "min_child_samples":      30,
    "feature_fraction":       0.6,
    "feature_fraction_bynode": 0.6,
    "bagging_fraction":       0.8,
    "bagging_freq":           5,
    "lambda_l1":              0.05,
    "lambda_l2":              0.05,
    "is_unbalance":           True,
    "verbose":                -1,
}

PRETRAIN_ROUNDS  = 3000
FINETUNE_ROUNDS  = 1500
EARLY_STOPPING   = 300


def load(path: str, target_col: str):
    log.info("Loading %s …", path)
    df = pd.read_csv(path)
    feature_cols = [c for c in df.columns
                    if c not in RAW_COLS and not c.startswith("target_")]
    df = df.dropna(subset=[target_col]).reset_index(drop=True)
    log.info("  %d rows  |  %d features", len(df), len(feature_cols))
    return df, feature_cols


def split(df):
    n = len(df)
    i_train = int(n * TRAIN_FRAC)
    i_val   = int(n * (TRAIN_FRAC + VAL_FRAC))
    return df.iloc[:i_train], df.iloc[i_train:i_val], df.iloc[i_val:]


def evaluate(booster, X, y, label):
    prob = booster.predict(X, num_iteration=booster.best_iteration)
    pred = (prob >= 0.5).astype(int)
    acc  = accuracy_score(y, pred)
    auc  = roc_auc_score(y, prob)
    log.info("  %s  accuracy=%.4f  AUC=%.4f", label, acc, auc)
    return acc, auc


def train_stage(name, dataset, val_dataset, num_rounds, init_model=None):
    log.info("── %s (%d rounds) ──────────────────────", name, num_rounds)
    callbacks = [lgb.early_stopping(EARLY_STOPPING, verbose=False), lgb.log_evaluation(50)]
    booster = lgb.train(
        LGB_PARAMS, dataset,
        num_boost_round=num_rounds,
        valid_sets=[val_dataset],
        callbacks=callbacks,
        init_model=init_model,
        keep_training_booster=True,
    )
    log.info("  Best iteration: %d  |  Total trees: %d", booster.best_iteration, booster.num_trees())
    return booster


def main(pretrain_paths, finetune_path, target_col, output_path):
    # ── Stage 1: pretrain ────────────────────────────────────────────────────
    frames = []
    feature_cols = None
    for p in pretrain_paths:
        df, fc = load(p, target_col)
        if feature_cols is None:
            feature_cols = fc
        frames.append(df)

    pre_df = pd.concat(frames).sample(frac=1, random_state=42).reset_index(drop=True)
    log.info("Pretrain dataset: %d rows from %d assets", len(pre_df), len(pretrain_paths))

    pre_train, pre_val, _ = split(pre_df)
    ds_pre     = lgb.Dataset(pre_train[feature_cols], label=pre_train[target_col],
                              feature_name=feature_cols, free_raw_data=True)
    ds_pre_val = lgb.Dataset(pre_val[feature_cols],   label=pre_val[target_col],
                              reference=ds_pre)

    booster = train_stage("Stage 1 — Pretrain", ds_pre, ds_pre_val, PRETRAIN_ROUNDS)
    evaluate(booster, pre_val[feature_cols], pre_val[target_col], "Pretrain val")

    # ── Stage 2: fine-tune on BTC ────────────────────────────────────────────
    ft_df, feature_cols = load(finetune_path, target_col)
    ft_train, ft_val, ft_test = split(ft_df)

    ds_ft     = lgb.Dataset(ft_train[feature_cols], label=ft_train[target_col],
                             feature_name=feature_cols, free_raw_data=True)
    ds_ft_val = lgb.Dataset(ft_val[feature_cols],   label=ft_val[target_col],
                             reference=ds_ft)

    booster = train_stage("Stage 2 — Fine-tune (BTC)", ds_ft, ds_ft_val,
                          FINETUNE_ROUNDS, init_model=booster)

    log.info("── Final evaluation ────────────────────────────────────")
    val_acc,  val_auc  = evaluate(booster, ft_val[feature_cols],  ft_val[target_col],  "Val ")
    test_acc, test_auc = evaluate(booster, ft_test[feature_cols], ft_test[target_col], "Test")

    # ── Save ─────────────────────────────────────────────────────────────────
    out = Path(output_path)
    ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_model  = out.parent / f"{out.stem}_{ts}{out.suffix}"
    out_report = out.parent / f"report_{out.stem}_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    booster.save_model(str(out_model))
    log.info("Model saved → %s  (%d trees)", out_model, booster.num_trees())

    importance = pd.Series(
        booster.feature_importance(importance_type="gain"),
        index=feature_cols,
    ).sort_values(ascending=False)

    report = {
        "target": target_col,
        "pretrain_files": pretrain_paths,
        "finetune_file":  finetune_path,
        "total_trees":    booster.num_trees(),
        "val":  {"accuracy": val_acc,  "auc": val_auc},
        "test": {"accuracy": test_acc, "auc": test_auc},
        "top20_features": importance.head(20).to_dict(),
    }
    out_report.write_text(json.dumps(report, indent=2))
    log.info("Report saved → %s", out_report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretrain", nargs="+", required=True,
                        help="Feature CSVs for pretraining (e.g. BTC + ETH)")
    parser.add_argument("--finetune", required=True,
                        help="Feature CSV for fine-tuning (BTC only)")
    parser.add_argument("--target",   default="target_dir_1bar")
    parser.add_argument("--output",   default="outputs/model_staged.txt")
    args = parser.parse_args()

    main(args.pretrain, args.finetune, args.target, args.output)
