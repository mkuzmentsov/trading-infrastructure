"""
Retrain the LightGBM BTC direction model on the last 1000 5-min candles from Binance.

Fetches data, computes features using the same pipeline as the bot, then continues
training the existing model (init_model) with 50 additional boosting rounds.

Usage:
    python ai/retrain.py --model /path/to/model.txt

The script imports compute_features / FEATURE_COLS / CANDLES_NEEDED directly from
the bot script so the feature pipeline stays in sync automatically.

Dependencies (same as the bot):
    pip install lightgbm pandas numpy pandas-ta requests
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("retrain")

# Import feature pipeline from the bot script
_BOT_SCRIPT = Path(__file__).parent.parent / "polymarket/k8s/helm/polymarket-btc-bot/files/scripts"
sys.path.insert(0, str(_BOT_SCRIPT))
from pm_btc import CANDLES_NEEDED, FEATURE_COLS, compute_features  # noqa: E402


def fetch_5m_candles(limit: int = 1000):
    import pandas as pd

    log.info("Fetching %d × 5m candles from Binance …", limit)
    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "5m", "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()

    df = pd.DataFrame(resp.json(), columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore",
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume", "trades"]].copy()
    df["timestamp"] = df["timestamp"] // 1000
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)

    # Drop the last (incomplete) candle
    return df.iloc[:-1].reset_index(drop=True)


def build_dataset(df):
    import pandas as pd

    labels = (df["close"].shift(-1) > df["close"]).astype(int)

    X_rows, y_rows = [], []
    for i in range(CANDLES_NEEDED, len(df) - 1):   # -1: last row has no label
        window = df.iloc[: i + 1]
        try:
            feat = compute_features(window)
        except Exception:
            continue
        if feat.isna().all():
            continue
        X_rows.append(feat.values)
        y_rows.append(labels.iloc[i])

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y_rows, dtype=np.int32)
    log.info("Dataset: %d samples, %.1f%% UP labels", len(y), 100 * y.mean())
    return X, y


def retrain(model_path: str, num_rounds: int = 50) -> None:
    df = fetch_5m_candles()
    X, y = build_dataset(df)

    if len(y) < 50:
        log.error("Only %d samples after warmup — aborting", len(y))
        sys.exit(1)

    dataset = lgb.Dataset(X, label=y, feature_name=FEATURE_COLS, free_raw_data=True)

    params = {
        "objective":     "binary",
        "metric":        "binary_logloss",
        "learning_rate": 0.02,
        "num_leaves":    31,
        "verbosity":     -1,
    }

    path = Path(model_path)
    init_model = lgb.Booster(model_file=str(path)) if path.exists() else None
    if init_model:
        log.info("Continuing from existing model (%d trees) at %s", init_model.num_trees(), path)
    else:
        log.info("No existing model found — training from scratch")

    booster = lgb.train(
        params,
        dataset,
        num_boost_round=num_rounds,
        init_model=init_model,
        keep_training_booster=True,
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = path.parent / f"{path.stem}_{ts}{path.suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_path))
    log.info("Saved model to %s (%d trees total)", out_path, booster.num_trees())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrain BTC direction model on latest Binance 5m data")
    parser.add_argument("--model", default="outputs/model.txt", help="Path to LightGBM model file")
    parser.add_argument("--rounds", type=int, default=50, help="Additional boosting rounds (default 50)")
    args = parser.parse_args()

    retrain(args.model, args.rounds)
