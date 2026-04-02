"""
Train V2: improved BTC 5m direction model.

Two strategies, both evaluated — best one is saved as the recommended model:

  v2a  Fine-tune the existing Kraken-pretrained model on recent Binance data.
       Uses only the features the Kraken model already knows about.
       Goal: adapt to current market regime without losing historical knowledge.

  v2b  Fresh model trained on Binance data with ALL features (including new
       Hurst / regime / extra-autocorrelation features).
       Goal: use richer feature set, even if the dataset is smaller.

Usage (defaults use the paths created by generate_features.py):
    python3 train_v2.py
    python3 train_v2.py --kraken_model outputs/kraken/BTC/features.csv  \\
                        --binance      outputs/binance/BTC/features.csv  \\
                        --target       target_dir_1bar
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
log = logging.getLogger("train_v2")

RAW_COLS = {"timestamp", "open", "high", "low", "close", "volume", "trades"}

# ── Hyperparameters ────────────────────────────────────────────────────────────

# v2a fine-tune: very conservative — we're adapting an existing model, not rewriting it
FINETUNE_PARAMS = {
    "objective":               "binary",
    "metric":                  ["binary_logloss", "auc"],
    "boosting_type":           "gbdt",
    "learning_rate":           0.005,   # very small — don't overwrite old knowledge
    "num_leaves":              31,
    "max_depth":               6,
    "min_child_samples":       40,
    "feature_fraction":        0.7,
    "feature_fraction_bynode": 0.7,
    "bagging_fraction":        0.8,
    "bagging_freq":            5,
    "lambda_l1":               0.3,
    "lambda_l2":               0.3,
    "min_gain_to_split":       0.02,
    "verbose":                 -1,
}
FINETUNE_ROUNDS   = 800
FINETUNE_EARLY    = 150

# v2b fresh: moderate complexity, heavy regularization for small dataset
FRESH_PARAMS = {
    "objective":               "binary",
    "metric":                  ["binary_logloss", "auc"],
    "boosting_type":           "dart",   # DART reduces overfitting better than gbdt on small data
    "learning_rate":           0.02,
    "num_leaves":              63,
    "max_depth":               7,
    "min_child_samples":       50,
    "feature_fraction":        0.6,
    "feature_fraction_bynode": 0.6,
    "bagging_fraction":        0.8,
    "bagging_freq":            5,
    "lambda_l1":               0.2,
    "lambda_l2":               0.2,
    "min_gain_to_split":       0.01,
    "drop_rate":               0.1,     # DART-specific
    "skip_drop":               0.5,     # DART-specific
    "is_unbalance":            True,
    "verbose":                 -1,
}
FRESH_ROUNDS = 2000
FRESH_EARLY  = 200


# ── Data helpers ───────────────────────────────────────────────────────────────

def load_features(path: str, target_col: str):
    log.info("Loading %s …", path)
    df = pd.read_csv(path)
    df = df.dropna(subset=[target_col]).reset_index(drop=True)
    feature_cols = [c for c in df.columns
                    if c not in RAW_COLS and not c.startswith("target_")]
    log.info("  %d rows  |  %d features", len(df), len(feature_cols))
    return df, feature_cols


def time_split(df, train_frac=0.70, val_frac=0.15):
    """Chronological split — no shuffling, respects time ordering."""
    n = len(df)
    i_train = int(n * train_frac)
    i_val   = int(n * (train_frac + val_frac))
    return df.iloc[:i_train], df.iloc[i_train:i_val], df.iloc[i_val:]


def evaluate(booster, X, y, label):
    num_iter = booster.best_iteration if booster.best_iteration > 0 else None
    prob = booster.predict(X, num_iteration=num_iter)
    pred = (prob >= 0.5).astype(int)
    acc  = accuracy_score(y, pred)
    auc  = roc_auc_score(y, prob)
    edge = np.abs(prob - 0.5)
    # accuracy at different edge thresholds
    for thr in [0.05, 0.10, 0.15, 0.20]:
        mask = edge >= thr
        if mask.sum() > 0:
            acc_thr = accuracy_score(y[mask], pred[mask])
            log.info("    edge≥%.2f  n=%d  acc=%.4f", thr, mask.sum(), acc_thr)
    log.info("  %-12s  accuracy=%.4f  AUC=%.4f", label, acc, auc)
    return acc, auc


# ── Strategy v2a: fine-tune existing model on Binance data ────────────────────

def train_v2a(kraken_model_path: str, binance_path: str, target_col: str):
    log.info("═" * 60)
    log.info("Strategy v2a — fine-tune Kraken model on Binance data")
    log.info("═" * 60)

    # Load existing pretrained model
    log.info("Loading pretrained model: %s", kraken_model_path)
    base_booster = lgb.Booster(model_file=kraken_model_path)
    base_features = base_booster.feature_name()
    log.info("  Pretrained model: %d trees | %d features",
             base_booster.num_trees(), len(base_features))

    # Load Binance features
    binance_df, all_features = load_features(binance_path, target_col)

    # Keep only features the pretrained model knows about
    common = [f for f in base_features if f in binance_df.columns]
    missing = [f for f in base_features if f not in binance_df.columns]
    if missing:
        log.warning("  %d features from pretrained model missing in Binance data: %s",
                    len(missing), missing[:5])
    log.info("  Using %d / %d pretrained features", len(common), len(base_features))

    train_df, val_df, test_df = time_split(binance_df)

    ds_train = lgb.Dataset(train_df[common], label=train_df[target_col],
                           feature_name=common, free_raw_data=True)
    ds_val   = lgb.Dataset(val_df[common],   label=val_df[target_col],
                           reference=ds_train)

    log.info("Fine-tuning for up to %d rounds (early stop %d) …",
             FINETUNE_ROUNDS, FINETUNE_EARLY)

    callbacks = [
        lgb.early_stopping(FINETUNE_EARLY, verbose=False),
        lgb.log_evaluation(100),
    ]
    booster = lgb.train(
        FINETUNE_PARAMS, ds_train,
        num_boost_round=FINETUNE_ROUNDS,
        valid_sets=[ds_val],
        callbacks=callbacks,
        init_model=base_booster,
        keep_training_booster=True,
    )
    log.info("  Total trees after fine-tune: %d  (added %d)",
             booster.num_trees(), booster.num_trees() - base_booster.num_trees())

    log.info("── Evaluation ──────────────────────────────────────────")
    val_acc,  val_auc  = evaluate(booster, val_df[common],  val_df[target_col].values,  "Val ")
    test_acc, test_auc = evaluate(booster, test_df[common], test_df[target_col].values, "Test")

    return booster, common, {
        "strategy": "v2a_finetune",
        "base_model": kraken_model_path,
        "features": len(common),
        "trees_total": booster.num_trees(),
        "val":  {"accuracy": val_acc,  "auc": val_auc},
        "test": {"accuracy": test_acc, "auc": test_auc},
    }


# ── Strategy v2b: fresh model with all features ───────────────────────────────

def train_v2b(binance_path: str, target_col: str):
    log.info("═" * 60)
    log.info("Strategy v2b — fresh DART model on Binance (all features)")
    log.info("═" * 60)

    df, feature_cols = load_features(binance_path, target_col)
    train_df, val_df, test_df = time_split(df)

    ds_train = lgb.Dataset(train_df[feature_cols], label=train_df[target_col],
                           feature_name=feature_cols, free_raw_data=True)
    ds_val   = lgb.Dataset(val_df[feature_cols],   label=val_df[target_col],
                           reference=ds_train)

    log.info("Training for up to %d rounds (early stop %d) …",
             FRESH_ROUNDS, FRESH_EARLY)

    # DART doesn't support early stopping reliably — use fixed rounds with a generous budget
    callbacks = [lgb.log_evaluation(200)]
    booster = lgb.train(
        FRESH_PARAMS, ds_train,
        num_boost_round=FRESH_ROUNDS,
        valid_sets=[ds_val],
        callbacks=callbacks,
    )

    log.info("── Evaluation ──────────────────────────────────────────")
    val_acc,  val_auc  = evaluate(booster, val_df[feature_cols],  val_df[target_col].values,  "Val ")
    test_acc, test_auc = evaluate(booster, test_df[feature_cols], test_df[target_col].values, "Test")

    importance = pd.Series(
        booster.feature_importance(importance_type="gain"),
        index=feature_cols,
    ).sort_values(ascending=False)

    return booster, feature_cols, {
        "strategy": "v2b_fresh_dart",
        "features": len(feature_cols),
        "trees_total": booster.num_trees(),
        "val":  {"accuracy": val_acc,  "auc": val_auc},
        "test": {"accuracy": test_acc, "auc": test_auc},
        "top20_features": importance.head(20).to_dict(),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kraken_model",
                        default="outputs/model_staged_20260330_105047.txt",
                        help="Path to existing pretrained LightGBM model (.txt)")
    parser.add_argument("--binance",
                        default="outputs/binance/BTC/features.csv",
                        help="Binance feature CSV (from generate_features.py)")
    parser.add_argument("--target", default="target_dir_1bar")
    parser.add_argument("--output_dir", default="outputs")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # ── v2a: fine-tune existing model ─────────────────────────────────────────
    if Path(args.kraken_model).exists():
        booster_a, feats_a, report_a = train_v2a(
            args.kraken_model, args.binance, args.target
        )
        path_a = out_dir / f"model_v2a_{ts}.txt"
        booster_a.save_model(str(path_a))
        log.info("v2a model saved → %s", path_a)
        results["v2a"] = report_a
    else:
        log.warning("Kraken model not found at %s — skipping v2a", args.kraken_model)
        booster_a, feats_a, path_a = None, None, None

    # ── v2b: fresh model ───────────────────────────────────────────────────────
    booster_b, feats_b, report_b = train_v2b(args.binance, args.target)
    path_b = out_dir / f"model_v2b_{ts}.txt"
    booster_b.save_model(str(path_b))
    log.info("v2b model saved → %s", path_b)
    results["v2b"] = report_b

    # ── Compare and pick winner ────────────────────────────────────────────────
    log.info("═" * 60)
    log.info("COMPARISON")
    log.info("═" * 60)
    for name, r in results.items():
        log.info("  %-6s  val_acc=%.4f  val_auc=%.4f  test_acc=%.4f  test_auc=%.4f  trees=%d",
                 name,
                 r["val"]["accuracy"], r["val"]["auc"],
                 r["test"]["accuracy"], r["test"]["auc"],
                 r["trees_total"])

    # Winner = highest test AUC (more reliable than accuracy for calibrated probs)
    winner = max(results, key=lambda k: results[k]["test"]["auc"])
    winner_path = path_a if winner == "v2a" else path_b
    log.info("  Winner: %s  (test AUC=%.4f)", winner, results[winner]["test"]["auc"])

    # Save report
    report_path = out_dir / f"report_v2_{ts}.json"
    report_path.write_text(json.dumps({
        "timestamp": ts,
        "target": args.target,
        "binance_data": args.binance,
        "winner": winner,
        "winner_model": str(winner_path),
        "results": results,
    }, indent=2))
    log.info("Report saved → %s", report_path)
    log.info("")
    log.info("  ✓ Best model: %s", winner_path)
    log.info("  Test with:  python3 test_model.py --model %s", winner_path)


if __name__ == "__main__":
    main()