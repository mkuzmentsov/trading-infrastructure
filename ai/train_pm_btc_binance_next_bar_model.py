from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, precision_score, recall_score, roc_auc_score

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "polymarket" / "k8s" / "helm" / "polymarket-btc-bot" / "files" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from btc_next_bar_model import FEATURE_COLUMNS, MIN_HISTORY_BARS, build_feature_row  # noqa: E402


RAW_COLUMNS = [
    "open_time_us",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_us",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]

LGB_PARAMS = {
    "objective": "binary",
    "metric": ["binary_logloss", "auc"],
    "learning_rate": 0.03,
    "num_leaves": 31,
    "max_depth": 6,
    "min_data_in_leaf": 120,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.9,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.2,
    "verbose": -1,
}


def _load_candles(paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        df = pd.read_csv(path, header=None, names=RAW_COLUMNS, usecols=[0, 1, 2, 3, 4, 5, 7, 8, 9])
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).sort_values("open_time_us").drop_duplicates("open_time_us").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base"):
        out[col] = out[col].astype(float)
    # Older files are in milliseconds, newer files in microseconds.
    ts = out["open_time_us"].astype("int64")
    out["start_ts"] = np.where(ts >= 10_000_000_000_000, ts // 1_000_000, ts // 1_000).astype(int)
    return out


def _build_dataset(df: pd.DataFrame) -> pd.DataFrame:
    bars = [
        {
            "start_ts": int(row.start_ts),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
            "quote_volume": float(row.quote_volume),
            "trade_count": float(row.trades),
            "taker_buy_volume": float(row.taker_buy_base),
        }
        for row in df.itertuples(index=False)
    ]

    rows: list[dict[str, float | int]] = []
    for idx in range(MIN_HISTORY_BARS - 1, len(bars) - 2):
        history = bars[max(0, idx + 1 - 64): idx + 1]
        target_bar = bars[idx + 1]
        next_bar = bars[idx + 2]
        feats = build_feature_row(history, market_start_ts=int(target_bar["start_ts"]))
        if feats is None:
            continue
        target_open = float(target_bar["open"])
        target_effective_close = float(next_bar["open"])
        feats["target"] = int(target_effective_close > target_open)
        feats["target_abs_body"] = abs(math_log_ratio(target_effective_close, target_open))
        feats["target_start_ts"] = int(target_bar["start_ts"])
        rows.append(feats)
    dataset = pd.DataFrame(rows)
    dataset["target_dt"] = pd.to_datetime(dataset["target_start_ts"], unit="s", utc=True)
    return dataset


def math_log_ratio(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return float(np.log(a / b))


def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def _time_split_recent(df: pd.DataFrame, years: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not years or years <= 0:
        return _time_split(df)
    cutoff = df["target_dt"].max() - pd.DateOffset(years=years)
    recent = df[df["target_dt"] >= cutoff].reset_index(drop=True)
    return _time_split(recent)


def _sample_weights(df: pd.DataFrame) -> np.ndarray:
    body = df["target_abs_body"].to_numpy(dtype=np.float32)
    scale = np.nanmedian(body)
    if not np.isfinite(scale) or scale <= 0:
        return np.ones(len(df), dtype=np.float32)
    return np.clip(body / scale, 0.8, 3.0).astype(np.float32)


def _metrics(y_true: np.ndarray, prob: np.ndarray) -> dict[str, float]:
    pred = (prob >= 0.5).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "auc": float(roc_auc_score(y_true, prob)),
        "logloss": float(log_loss(y_true, np.clip(prob, 1e-6, 1 - 1e-6))),
        "brier": float(brier_score_loss(y_true, prob)),
        "mean_pred": float(np.mean(prob)),
        "mean_label": float(np.mean(y_true)),
    }


def _threshold_table(y_true: np.ndarray, prob: np.ndarray) -> dict[str, list[dict[str, float | int]]]:
    up_rows: list[dict[str, float | int]] = []
    down_rows: list[dict[str, float | int]] = []
    for threshold in np.arange(0.52, 0.66, 0.02):
        mask = prob >= threshold
        count = int(mask.sum())
        precision = float((y_true[mask] == 1).mean()) if count else 0.0
        up_rows.append({
            "threshold": round(float(threshold), 3),
            "coverage": round(float(count / len(y_true)), 4),
            "signal_count": count,
            "precision": round(precision, 4),
        })
    for threshold in np.arange(0.48, 0.34, -0.02):
        mask = prob <= threshold
        count = int(mask.sum())
        precision = float((y_true[mask] == 0).mean()) if count else 0.0
        down_rows.append({
            "threshold": round(float(threshold), 3),
            "coverage": round(float(count / len(y_true)), 4),
            "signal_count": count,
            "precision": round(precision, 4),
        })
    return {"up": up_rows, "down": down_rows}


def train_model(dataset: pd.DataFrame, output_dir: Path, recent_years: int | None = None, model_name: str = "pm_btc_binance_next_bar_model") -> dict[str, object]:
    train_df, val_df, test_df = _time_split_recent(dataset, years=recent_years)

    ds_train = lgb.Dataset(
        train_df[FEATURE_COLUMNS],
        label=train_df["target"],
        weight=_sample_weights(train_df),
        feature_name=FEATURE_COLUMNS,
        free_raw_data=True,
    )
    ds_val = lgb.Dataset(
        val_df[FEATURE_COLUMNS],
        label=val_df["target"],
        weight=_sample_weights(val_df),
        reference=ds_train,
        free_raw_data=True,
    )

    booster = lgb.train(
        LGB_PARAMS,
        ds_train,
        num_boost_round=1200,
        valid_sets=[ds_val],
        callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(100)],
    )

    val_prob = booster.predict(val_df[FEATURE_COLUMNS], num_iteration=booster.best_iteration)
    test_prob = booster.predict(test_df[FEATURE_COLUMNS], num_iteration=booster.best_iteration)
    val_y = val_df["target"].to_numpy(dtype=np.int32)
    test_y = test_df["target"].to_numpy(dtype=np.int32)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{model_name}.txt"
    meta_path = output_dir / f"{model_name}_meta.json"
    booster.save_model(str(model_path))

    top_features = (
        pd.Series(booster.feature_importance(importance_type="gain"), index=FEATURE_COLUMNS)
        .sort_values(ascending=False)
        .head(20)
        .to_dict()
    )
    report: dict[str, object] = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_rows": int(len(dataset)),
        "training_rows": int(len(train_df) + len(val_df) + len(test_df)),
        "recent_years": int(recent_years or 0),
        "date_range": {
            "start": str(train_df["target_dt"].iloc[0]),
            "end": str(test_df["target_dt"].iloc[-1]),
        },
        "splits": {
            "train_rows": int(len(train_df)),
            "val_rows": int(len(val_df)),
            "test_rows": int(len(test_df)),
        },
        "best_iteration": int(booster.best_iteration or booster.num_trees()),
        "features": FEATURE_COLUMNS,
        "metrics": {
            "validation": _metrics(val_y, val_prob),
            "test": _metrics(test_y, test_prob),
        },
        "threshold_tables": {
            "validation": _threshold_table(val_y, val_prob),
            "test": _threshold_table(test_y, test_prob),
        },
        "top_features": {k: float(v) for k, v in top_features.items()},
        "model_path": str(model_path),
    }
    meta_path.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a PM BTC-compatible Binance 5m next-bar prior model")
    parser.add_argument(
        "--input-glob",
        default="/Users/maxkuzmentsov/development/projects/my/5m/BTCUSDT-5m-*.csv",
        help="Glob for Binance monthly 5m CSV files",
    )
    parser.add_argument(
        "--output-dir",
        default="ai/outputs/pm_btc_binance_next_bar",
        help="Directory for the trained model and metadata",
    )
    parser.add_argument(
        "--recent-years",
        type=int,
        default=3,
        help="Use only the most recent N years of data before chronological split; 0 means all history",
    )
    parser.add_argument(
        "--model-name",
        default="pm_btc_binance_next_bar_model",
        help="Output model basename",
    )
    args = parser.parse_args()

    paths = sorted(glob.glob(args.input_glob))
    if not paths:
        raise SystemExit(f"No files matched {args.input_glob}")

    candles = _load_candles(paths)
    dataset = _build_dataset(candles)
    report = train_model(dataset, Path(args.output_dir), recent_years=args.recent_years, model_name=args.model_name)

    test_metrics = report["metrics"]["test"]
    print(
        json.dumps(
            {
                "model_path": report["model_path"],
                "test_accuracy": round(test_metrics["accuracy"], 4),
                "test_auc": round(test_metrics["auc"], 4),
                "test_logloss": round(test_metrics["logloss"], 4),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
