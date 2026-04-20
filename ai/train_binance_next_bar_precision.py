"""
Train a precision-first BTCUSDT 5m next-bar direction model on Binance history.

This script is intended for strategy gating, not raw always-on prediction.
It trains a LightGBM classifier on the repo's OHLCV feature set, then selects
UP and DOWN probability thresholds on a validation split to maximize precision
while keeping enough signal count to matter in production.

Typical usage:
    python3 ai/train_binance_next_bar_precision.py \
        --input-glob 'ai/inputs/binance/btc/5m/BTCUSDT-5m-*.csv' \
        --output-dir ai/outputs/binance_btc_precision
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, precision_score, recall_score, roc_auc_score

from generate_features import (
    _load_csv,
    _validate_and_clean,
    add_microstructure,
    add_momentum,
    add_moving_averages,
    add_multitimeframe,
    add_price_features,
    add_regime_features,
    add_statistical_features,
    add_target,
    add_time_features,
    add_trend_features,
    add_volatility,
    add_volume_features,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("train_binance_next_bar_precision")

RAW_COLS = {"timestamp", "open", "high", "low", "close", "volume", "trades"}
WARMUP_ROWS = 200
TRAIN_FRAC = 0.70
VAL_FRAC = 0.15

LGB_PARAMS = {
    "objective": "binary",
    "metric": ["binary_logloss", "auc"],
    "boosting_type": "gbdt",
    "learning_rate": 0.03,
    "num_leaves": 63,
    "max_depth": 7,
    "min_child_samples": 80,
    "feature_fraction": 0.7,
    "feature_fraction_bynode": 0.7,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.2,
    "lambda_l2": 0.4,
    "min_gain_to_split": 0.01,
    "verbose": -1,
}
NUM_BOOST_ROUND = 2000
EARLY_STOPPING = 200


@dataclass
class ThresholdChoice:
    side: str
    threshold: float
    precision: float
    recall: float
    coverage: float
    signal_count: int

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "side": self.side,
            "threshold": round(self.threshold, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "coverage": round(self.coverage, 4),
            "signal_count": self.signal_count,
        }


def _load_all_candles(input_paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in input_paths:
        log.info("Loading %s", path)
        frames.append(_load_csv(path))
    df = (
        pd.concat(frames, ignore_index=True)
        .sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )
    log.info("Loaded %s raw candles before cleaning", f"{len(df):,}")
    df = _validate_and_clean(df)
    log.info("Remaining candles after cleaning: %s", f"{len(df):,}")
    return df


def _add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["timestamp_dt_mtf"] = df["timestamp_dt"]

    steps = [
        add_price_features,
        add_moving_averages,
        add_momentum,
        add_volatility,
        add_volume_features,
        add_trend_features,
        add_statistical_features,
        add_regime_features,
        add_time_features,
        add_multitimeframe,
        add_microstructure,
        add_target,
    ]
    for fn in steps:
        log.info("Adding %s", fn.__name__)
        df = fn(df)
    df = df.iloc[WARMUP_ROWS:].reset_index(drop=True)
    return df


def _build_dataset(input_paths: list[str]) -> pd.DataFrame:
    candles = _load_all_candles(input_paths)
    feat_df = _add_all_features(candles)
    feat_df = feat_df.dropna(subset=["target_dir_1bar"]).reset_index(drop=True)
    feat_df["target_dir_1bar"] = feat_df["target_dir_1bar"].astype(int)
    feat_df["abs_target_ret_1bar"] = feat_df["target_ret_1bar"].abs()
    return feat_df


def _feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        c for c in df.columns
        if c not in RAW_COLS
        and not c.startswith("target_")
        and c not in {"timestamp_dt_mtf", "abs_target_ret_1bar"}
    ]


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    i_train = int(n * TRAIN_FRAC)
    i_val = int(n * (TRAIN_FRAC + VAL_FRAC))
    return df.iloc[:i_train], df.iloc[i_train:i_val], df.iloc[i_val:]


def _sample_weights(df: pd.DataFrame) -> np.ndarray:
    move = df["abs_target_ret_1bar"].to_numpy(dtype=np.float32)
    scale = np.nanmedian(move)
    if not np.isfinite(scale) or scale <= 0:
        return np.ones(len(df), dtype=np.float32)
    weights = np.clip(move / scale, 0.75, 4.0)
    return weights.astype(np.float32)


def _metrics(y_true: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    pred = (prob >= threshold).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "auc": float(roc_auc_score(y_true, prob)),
        "logloss": float(log_loss(y_true, np.clip(prob, 1e-6, 1 - 1e-6))),
    }


def _select_thresholds(
    y_true: np.ndarray,
    prob: np.ndarray,
    min_signals: int,
) -> tuple[ThresholdChoice, ThresholdChoice, list[dict[str, float | int | str]]]:
    candidates: list[dict[str, float | int | str]] = []

    def choose(side: str, threshold_grid: list[float]) -> ThresholdChoice:
        best: ThresholdChoice | None = None
        for threshold in threshold_grid:
            if side == "UP":
                mask = prob >= threshold
                positive_label = 1
            else:
                mask = prob <= threshold
                positive_label = 0
            signal_count = int(mask.sum())
            if signal_count < min_signals:
                continue
            y_sel = y_true[mask]
            precision = float((y_sel == positive_label).mean()) if signal_count else 0.0
            recall = float(((y_true == positive_label) & mask).sum() / max((y_true == positive_label).sum(), 1))
            coverage = signal_count / len(y_true)
            row = {
                "side": side,
                "threshold": round(float(threshold), 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "coverage": round(coverage, 4),
                "signal_count": signal_count,
            }
            candidates.append(row)
            choice = ThresholdChoice(
                side=side,
                threshold=float(threshold),
                precision=precision,
                recall=recall,
                coverage=coverage,
                signal_count=signal_count,
            )
            if best is None:
                best = choice
                continue
            if choice.precision > best.precision + 1e-12:
                best = choice
                continue
            if abs(choice.precision - best.precision) <= 1e-12 and choice.coverage > best.coverage:
                best = choice
                continue
        if best is None:
            fallback_threshold = 0.55 if side == "UP" else 0.45
            mask = prob >= fallback_threshold if side == "UP" else prob <= fallback_threshold
            signal_count = int(mask.sum())
            y_sel = y_true[mask]
            positive_label = 1 if side == "UP" else 0
            precision = float((y_sel == positive_label).mean()) if signal_count else 0.0
            recall = float(((y_true == positive_label) & mask).sum() / max((y_true == positive_label).sum(), 1))
            coverage = signal_count / len(y_true)
            best = ThresholdChoice(side, fallback_threshold, precision, recall, coverage, signal_count)
        return best

    up_grid = [round(x, 3) for x in np.arange(0.52, 0.801, 0.01)]
    down_grid = [round(x, 3) for x in np.arange(0.48, 0.199, -0.01)]
    best_up = choose("UP", up_grid)
    best_down = choose("DOWN", down_grid)
    return best_up, best_down, candidates


def _threshold_metrics(y_true: np.ndarray, prob: np.ndarray, threshold: ThresholdChoice) -> dict[str, float | int]:
    if threshold.side == "UP":
        mask = prob >= threshold.threshold
        correct = y_true[mask] == 1
    else:
        mask = prob <= threshold.threshold
        correct = y_true[mask] == 0
    signal_count = int(mask.sum())
    return {
        "signal_count": signal_count,
        "coverage": float(signal_count / len(y_true)),
        "precision": float(correct.mean()) if signal_count else 0.0,
    }


def train_model(df: pd.DataFrame, output_dir: Path, save_features: bool) -> dict[str, object]:
    feature_cols = _feature_columns(df)
    train_df, val_df, test_df = _time_split(df)

    if save_features:
        features_path = output_dir / "binance_btc_5m_nextbar_features.parquet"
        output_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(features_path, index=False)
        log.info("Saved feature frame to %s", features_path)

    ds_train = lgb.Dataset(
        train_df[feature_cols],
        label=train_df["target_dir_1bar"],
        weight=_sample_weights(train_df),
        feature_name=feature_cols,
        free_raw_data=True,
    )
    ds_val = lgb.Dataset(
        val_df[feature_cols],
        label=val_df["target_dir_1bar"],
        weight=_sample_weights(val_df),
        reference=ds_train,
    )

    log.info(
        "Training on %s rows, validating on %s, testing on %s",
        f"{len(train_df):,}",
        f"{len(val_df):,}",
        f"{len(test_df):,}",
    )
    booster = lgb.train(
        LGB_PARAMS,
        ds_train,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[ds_val],
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING, verbose=False),
            lgb.log_evaluation(100),
        ],
    )

    val_prob = booster.predict(val_df[feature_cols], num_iteration=booster.best_iteration)
    test_prob = booster.predict(test_df[feature_cols], num_iteration=booster.best_iteration)
    val_y = val_df["target_dir_1bar"].to_numpy(dtype=np.int32)
    test_y = test_df["target_dir_1bar"].to_numpy(dtype=np.int32)

    min_signals = max(250, int(len(val_df) * 0.01))
    best_up, best_down, threshold_grid = _select_thresholds(val_y, val_prob, min_signals=min_signals)

    importance = (
        pd.Series(booster.feature_importance(importance_type="gain"), index=feature_cols)
        .sort_values(ascending=False)
        .head(30)
        .to_dict()
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"btc_5m_nextbar_precision_model_{ts}.txt"
    report_path = output_dir / f"btc_5m_nextbar_precision_report_{ts}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(model_path))

    report: dict[str, object] = {
        "timestamp": ts,
        "dataset_rows": len(df),
        "feature_count": len(feature_cols),
        "date_range": {
            "start": str(pd.to_datetime(df["timestamp"].iloc[0], unit="s", utc=True)),
            "end": str(pd.to_datetime(df["timestamp"].iloc[-1], unit="s", utc=True)),
        },
        "splits": {
            "train_rows": len(train_df),
            "val_rows": len(val_df),
            "test_rows": len(test_df),
        },
        "best_iteration": int(booster.best_iteration or booster.num_trees()),
        "metrics": {
            "validation": _metrics(val_y, val_prob),
            "test": _metrics(test_y, test_prob),
        },
        "selected_thresholds": {
            "up": best_up.as_dict(),
            "down": best_down.as_dict(),
        },
        "threshold_performance": {
            "validation": {
                "up": _threshold_metrics(val_y, val_prob, best_up),
                "down": _threshold_metrics(val_y, val_prob, best_down),
            },
            "test": {
                "up": _threshold_metrics(test_y, test_prob, best_up),
                "down": _threshold_metrics(test_y, test_prob, best_down),
            },
        },
        "threshold_grid": threshold_grid,
        "top_features": {k: float(v) for k, v in importance.items()},
        "model_path": str(model_path),
    }
    report_path.write_text(json.dumps(report, indent=2))

    log.info("Saved model to %s", model_path)
    log.info("Saved report to %s", report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a precision-first BTCUSDT 5m next-bar classifier")
    parser.add_argument(
        "--input-glob",
        default="ai/inputs/binance/btc/5m/BTCUSDT-5m-*.csv",
        help="Glob for Binance monthly 5m CSV files",
    )
    parser.add_argument(
        "--output-dir",
        default="ai/outputs/binance_btc_precision",
        help="Where to write the model and report",
    )
    parser.add_argument(
        "--save-features",
        action="store_true",
        help="Also save the engineered feature frame as parquet",
    )
    args = parser.parse_args()

    input_paths = sorted(glob.glob(args.input_glob))
    if not input_paths:
        raise SystemExit(f"No files matched {args.input_glob}")
    log.info("Matched %d raw Binance files", len(input_paths))

    dataset = _build_dataset(input_paths)
    report = train_model(dataset, Path(args.output_dir), save_features=args.save_features)

    test_metrics = report["metrics"]["test"]
    selected = report["selected_thresholds"]
    log.info(
        "Test accuracy=%.4f AUC=%.4f | recommended thresholds: UP>=%.2f DOWN<=%.2f",
        test_metrics["accuracy"],
        test_metrics["auc"],
        selected["up"]["threshold"],
        selected["down"]["threshold"],
    )


if __name__ == "__main__":
    main()
