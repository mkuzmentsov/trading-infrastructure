"""
Train a LightGBM classifier on the feature matrix produced by generate_features.py.

Usage:
    pip install lightgbm scikit-learn
    python train_model.py [--input BTCUSD_features.csv] [--target target_dir_15m]

Outputs:
    model_<target>_<date>.txt   — LightGBM model (text format, load with lgb.Booster)
    report_<target>_<date>.txt  — eval metrics + top-20 features
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    roc_auc_score,
)

# ── Config ─────────────────────────────────────────────────────────────────────

RAW_COLS     = {"timestamp", "open", "high", "low", "close", "volume", "trades"}
TRAIN_FRAC   = 0.70
VAL_FRAC     = 0.15
# test = remaining 15 %

LGB_PARAMS = {
    "objective":        "binary",
    "metric":           ["binary_logloss", "auc"],
    "boosting_type":    "gbdt",
    "learning_rate":    0.05,
    "num_leaves":       63,
    "min_child_samples": 50,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     5,
    "lambda_l1":        0.1,
    "lambda_l2":        0.1,
    "verbose":          -1,
}

NUM_BOOST_ROUND  = 500
EARLY_STOPPING   = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def split(df: pd.DataFrame):
    n = len(df)
    i_train = int(n * TRAIN_FRAC)
    i_val   = int(n * (TRAIN_FRAC + VAL_FRAC))
    return df.iloc[:i_train], df.iloc[i_train:i_val], df.iloc[i_val:]


# ── Main ───────────────────────────────────────────────────────────────────────

def main(input_path: str, target_col: str) -> None:
    print(f"Loading {input_path} …")
    df = pd.read_csv(input_path)
    print(f"  {len(df):,} rows × {df.shape[1]} columns")

    # Validate target
    target_cols_all = [c for c in df.columns if c.startswith("target_")]
    if target_col not in df.columns:
        raise ValueError(
            f"Target '{target_col}' not found. Available: {target_cols_all}"
        )

    # Feature columns = everything except raw OHLCV, timestamp, and all targets
    feature_cols = [
        c for c in df.columns
        if c not in RAW_COLS and not c.startswith("target_")
    ]
    print(f"  Features: {len(feature_cols)}  |  Target: {target_col}")

    # Drop rows with NaN in target
    df = df.dropna(subset=[target_col]).reset_index(drop=True)

    train_df, val_df, test_df = split(df)
    print(
        f"  Split → train {len(train_df):,} / val {len(val_df):,} / test {len(test_df):,}"
    )

    X_train, y_train = train_df[feature_cols], train_df[target_col]
    X_val,   y_val   = val_df[feature_cols],   val_df[target_col]
    X_test,  y_test  = test_df[feature_cols],  test_df[target_col]

    dtrain = lgb.Dataset(X_train, label=y_train, feature_name=feature_cols)
    dval   = lgb.Dataset(X_val,   label=y_val,   reference=dtrain)

    print(f"\nTraining LightGBM  (up to {NUM_BOOST_ROUND} rounds, early stop {EARLY_STOPPING}) …")
    callbacks = [
        lgb.early_stopping(EARLY_STOPPING, verbose=False),
        lgb.log_evaluation(50),
    ]
    booster = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[dval],
        callbacks=callbacks,
    )

    best_iter = booster.best_iteration
    print(f"  Best iteration: {best_iter}")

    # ── Evaluation ──
    def evaluate(X, y, split_name):
        prob = booster.predict(X, num_iteration=best_iter)
        pred = (prob >= 0.5).astype(int)
        acc  = accuracy_score(y, pred)
        auc  = roc_auc_score(y, prob)
        print(f"\n{split_name}  accuracy={acc:.4f}  AUC={auc:.4f}")
        print(classification_report(y, pred, target_names=["DOWN", "UP"], digits=4))
        return {"accuracy": acc, "auc": auc}

    val_metrics  = evaluate(X_val,  y_val,  "Val ")
    test_metrics = evaluate(X_test, y_test, "Test")

    # ── Feature importance ──
    importance = pd.Series(
        booster.feature_importance(importance_type="gain"),
        index=feature_cols,
    ).sort_values(ascending=False)
    print("\nTop 20 features by gain:")
    print(importance.head(20).to_string())

    # ── Save ──
    date_str = datetime.now().strftime("%Y%m%d")
    model_path  = Path(f"model_{target_col}_{date_str}.txt")
    report_path = Path(f"report_{target_col}_{date_str}.txt")

    booster.save_model(str(model_path))
    print(f"\nModel saved → {model_path}")

    report = {
        "target":        target_col,
        "features":      len(feature_cols),
        "best_iteration": best_iter,
        "train_rows":    len(train_df),
        "val_rows":      len(val_df),
        "test_rows":     len(test_df),
        "val":           val_metrics,
        "test":          test_metrics,
        "top20_features": importance.head(20).to_dict(),
        "lgb_params":    LGB_PARAMS,
    }
    report_path.write_text(json.dumps(report, indent=2))
    print(f"Report saved  → {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="BTCUSD_features.csv")
    parser.add_argument(
        "--target", default="target_dir_15m",
        help="Target column: target_dir_5m / 15m / 60m / 240m  or  target_ret_*",
    )
    args = parser.parse_args()
    main(args.input, args.target)
