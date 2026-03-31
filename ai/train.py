"""
Train a new LightGBM BTC direction model from a Binance 5m klines CSV.

Expects the standard Binance klines format (no header):
  open_time(us), open, high, low, close, volume, close_time(us),
  quote_vol, trades, taker_base, taker_quote, ignore

Label: 1 if close[i+1] > close[i] (next 5m bar closes up), else 0.

Usage:
    python ai/train.py --input ai/inputs/BINANCE_5m_2025-12_2026-02.csv
    python ai/train.py --input ai/inputs/BINANCE_5m_2025-12_2026-02.csv --output ai/model.txt --rounds 300
"""

import argparse
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("train")

# Import feature pipeline from the bot script
_BOT_SCRIPT = Path(__file__).parent.parent / "polymarket/k8s/helm/polymarket-btc-bot/files/scripts"
sys.path.insert(0, str(_BOT_SCRIPT))
from pm_btc import (  # noqa: E402
    CANDLES_NEEDED, FEATURE_COLS,
    _add_price, _add_ma, _add_momentum, _add_volatility,
    _add_volume, _add_trend, _add_statistical, _add_time, _add_mtf,
)


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, names=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume", "trades"]].copy()
    df["timestamp"] = df["timestamp"] // 1_000_000   # microseconds → seconds
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)
    df = df.reset_index(drop=True)
    log.info("Loaded %d rows from %s", len(df), path)
    return df


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    dt = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = _add_price(df)
    df = _add_ma(df)
    df = _add_momentum(df)
    df = _add_volatility(df)
    df = _add_volume(df)
    df = _add_trend(df)
    df = _add_statistical(df)
    df = _add_time(df, dt)
    df = _add_mtf(df, dt)
    return df


def build_dataset(df: pd.DataFrame):
    # Label: 1 if next bar closes higher
    labels = (df["close"].shift(-1) > df["close"]).astype(int)

    feat_df = compute_all_features(df)

    # Drop warmup rows and the last row (no label)
    valid = feat_df[FEATURE_COLS].iloc[CANDLES_NEEDED:-1]
    y = labels.iloc[CANDLES_NEEDED:-1].values

    X = valid.values.astype(np.float32)
    log.info("Dataset: %d samples, %.1f%% UP labels", len(y), 100 * y.mean())
    return X, y


def train(input_path: str, output_path: str, num_rounds: int) -> None:
    df = load_csv(input_path)
    X, y = build_dataset(df)

    if len(y) < 100:
        log.error("Only %d samples — aborting", len(y))
        sys.exit(1)

    dataset = lgb.Dataset(X, label=y, feature_name=FEATURE_COLS, free_raw_data=True)

    params = {
        "objective":      "binary",
        "metric":         "binary_logloss",
        "learning_rate":  0.02,
        "num_leaves":     31,
        "min_child_samples": 20,
        "feature_fraction":  0.8,
        "bagging_fraction":  0.8,
        "bagging_freq":      5,
        "verbosity":      -1,
    }

    log.info("Training %d rounds on %d samples …", num_rounds, len(y))
    booster = lgb.train(params, dataset, num_boost_round=num_rounds)

    # Save with timestamp suffix
    out = Path(output_path)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out.parent / f"{out.stem}_{ts}{out.suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_path))
    log.info("Saved model to %s (%d trees)", out_path, booster.num_trees())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train BTC 5m direction model from Binance klines CSV")
    parser.add_argument("--input",  default="ai/inputs/BINANCE_5m_2025-12_2026-02.csv", help="Path to klines CSV")
    parser.add_argument("--output", default="outputs/model.txt", help="Output model path (timestamp will be appended)")
    parser.add_argument("--rounds", type=int, default=200, help="Boosting rounds (default 200)")
    args = parser.parse_args()

    train(args.input, args.output, args.rounds)
