"""
Backtest the LightGBM BTC 5-min direction model on recent data.

What it does:
  1. Fetches the last 1000 5-minute BTC/USDT candles from Binance (~83h, public, no API key).
  2. Computes all 107 features using generate_features.py (same code as production).
  3. Predicts UP/DOWN for each candle, checks actual result.
  4. Prints a clean stats table.

Usage:
    python test_model.py [--model outputs/model_target_dir_1bar_20260328.txt] [--edge 0.05]
"""

import argparse
import sys
from glob import glob
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests

# ── Reuse feature engineering from generate_features.py ───────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from generate_features import (
    add_price_features,
    add_moving_averages,
    add_momentum,
    add_volatility,
    add_volume_features,
    add_trend_features,
    add_statistical_features,
    add_time_features,
    add_multitimeframe,
    add_microstructure,
)

FEATURE_COLS_EXCLUDE = {"timestamp", "open", "high", "low", "close", "volume", "trades",
                         "timestamp_dt", "timestamp_dt_mtf"}

WARMUP  = 200  # rows to skip (longest indicator lookback)
HORIZON = 1    # bars ahead to check actual direction (1 bar = 5 min)


def fetch_binance_5m(n: int = 1000) -> pd.DataFrame:
    print(f"Fetching {n} 5-min BTC/USDT candles from Binance …")
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "5m", "limit": n},
        timeout=30,
    )
    r.raise_for_status()
    cols = ["timestamp","open","high","low","close","volume",
            "close_time","quote_vol","trades",
            "taker_buy_vol","taker_buy_quote_vol","ignore"]
    df = pd.DataFrame(r.json(), columns=cols)
    df["timestamp"] = df["timestamp"].astype(int) // 1000
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["trades"] = df["trades"].astype(int)
    return df[["timestamp","open","high","low","close","volume","trades"]]


def build_features_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """Run the full feature pipeline on an in-memory DataFrame (no CSV I/O)."""
    df = df.copy().reset_index(drop=True)
    df["timestamp_dt"]     = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["timestamp_dt_mtf"] = df["timestamp_dt"]

    for fn in [add_price_features, add_moving_averages, add_momentum,
               add_volatility, add_volume_features, add_trend_features,
               add_statistical_features, add_time_features, add_multitimeframe,
               add_microstructure]:
        df = fn(df)

    return df.iloc[WARMUP:].reset_index(drop=True)


def run_backtest(df_feat: pd.DataFrame, booster: lgb.Booster,
                 min_edge: float) -> pd.DataFrame:
    feature_cols = [c for c in df_feat.columns if c not in FEATURE_COLS_EXCLUDE
                    and not c.startswith("target_")]

    records = []
    close = df_feat["close"].values

    # All rows are 5m candles — evaluate every row except last (no actual result yet)
    eval_indices = list(range(len(df_feat) - HORIZON))

    for i in eval_indices:
        row    = df_feat.iloc[i]
        ts     = pd.to_datetime(row["timestamp"], unit="s", utc=True)
        x      = row[feature_cols].values.reshape(1, -1)
        p_up   = float(booster.predict(x)[0])
        actual = int(close[i + HORIZON] >= close[i])   # 1=Up, 0=Down
        edge   = abs(p_up - 0.5)

        records.append({
            "time":    ts.strftime("%H:%M"),
            "close":   close[i],
            "p_up":    p_up,
            "pred":    int(p_up >= 0.5),
            "actual":  actual,
            "correct": int((p_up >= 0.5) == actual),
            "edge":    edge,
            "bet":     int(edge >= min_edge),
        })

    return pd.DataFrame(records)


def print_stats(results: pd.DataFrame, min_edge: float) -> None:
    total  = len(results)
    bets   = results[results["bet"] == 1]
    n_bets = len(bets)

    acc_all = results["correct"].mean()
    acc_bet = bets["correct"].mean() if n_bets else float("nan")
    pnl     = (bets["correct"] * 2 - 1).sum()

    # UP / DOWN win rates
    up_bets   = bets[bets["pred"] == 1]
    down_bets = bets[bets["pred"] == 0]
    up_won    = up_bets["correct"].mean()   if len(up_bets)   else float("nan")
    down_won  = down_bets["correct"].mean() if len(down_bets) else float("nan")

    print("\n" + "=" * 52)
    print(f"  Backtest Results  (last {total} × 5m candles ≈ {total * 5 // 60}h)")
    print("=" * 52)
    print(f"  Total ticks evaluated : {total}")
    print(f"  Ticks with edge≥{min_edge:.2f} : {n_bets}  ({n_bets/total*100:.1f}%)")
    print(f"  Accuracy (all ticks)  : {acc_all:.2%}")
    print(f"  Accuracy (bet ticks)  : {acc_bet:.2%}")
    print(f"  UP   bets won         : {up_won:.2%}  ({len(up_bets)} bets)")
    print(f"  DOWN bets won         : {down_won:.2%}  ({len(down_bets)} bets)")
    print(f"  Net units P&L (bets)  : {pnl:+.0f}  (@ $1/bet)")
    print("=" * 52)

    # Per-confidence-bucket breakdown
    print("\n  Edge bucket breakdown:")
    print(f"  {'Edge ≥':>8}  {'Ticks':>6}  {'Accuracy':>9}  {'UP won':>8}  {'DOWN won':>9}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*9}")
    for threshold in [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
        subset = results[results["edge"] >= threshold]
        if not len(subset):
            continue
        s_up   = subset[subset["pred"] == 1]
        s_down = subset[subset["pred"] == 0]
        u = f"{s_up['correct'].mean():.2%}"   if len(s_up)   else "  n/a  "
        d = f"{s_down['correct'].mean():.2%}" if len(s_down) else "  n/a  "
        print(f"  {threshold:>8.2f}  {len(subset):>6}  {subset['correct'].mean():>9.2%}  {u:>8}  {d:>9}")
    print()

    # Last 50 ticks (all), with bet indicator
    last = results.tail(50)
    print(f"  Last {len(last)} ticks:")
    print(f"  {'Time':>6}  {'Close':>9}  {'P(UP)':>6}  {'Pred':>5}  {'Actual':>6}  {'OK':>3}  {'Bet':>3}")
    print(f"  {'-'*6}  {'-'*9}  {'-'*6}  {'-'*5}  {'-'*6}  {'-'*3}  {'-'*3}")
    for _, row in last.iterrows():
        direction = "UP  " if row["pred"] else "DOWN"
        actual    = "UP  " if row["actual"] else "DOWN"
        ok        = "✓" if row["correct"] else "✗"
        bet       = "•" if row["bet"] else ""
        print(f"  {row['time']:>6}  {row['close']:>9.2f}  {row['p_up']:>6.3f}  {direction}  {actual}  {ok:>3}  {bet:>3}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None,
                        help="Path to LightGBM model .txt (defaults to latest in current dir)")
    parser.add_argument("--edge",  type=float, default=0.05,
                        help="Min edge (|P-0.5|) to count as a bet (default 0.05)")
    parser.add_argument("--candles", type=int, default=1000,
                        help="5-min candles to fetch (default 1000 ≈ 83h)")
    args = parser.parse_args()

    # Find model
    model_path = args.model
    if model_path is None:
        candidates = sorted(glob("outputs/model_target_dir_*.txt"))
        if not candidates:
            print("No model file found. Train one with: python train_model.py --target target_dir_1bar")
            sys.exit(1)
        model_path = candidates[-1]
    print(f"Model: {model_path}")
    booster = lgb.Booster(model_file=model_path)

    # Data
    raw = fetch_binance_5m(args.candles)
    print(f"Fetched {len(raw)} rows | {raw['timestamp'].iloc[0]} → {raw['timestamp'].iloc[-1]}")

    print("Computing features …")
    df_feat = build_features_from_df(raw)
    print(f"Feature matrix: {len(df_feat)} rows × {len(df_feat.columns)} cols")

    print("Running backtest …")
    results = run_backtest(df_feat, booster, min_edge=args.edge)

    print_stats(results, min_edge=args.edge)


if __name__ == "__main__":
    main()
