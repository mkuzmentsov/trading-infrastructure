"""
Backtest Chronos-2 (120M) on BTC 5m direction prediction.

Chronos-2 produces quantile forecasts.  We convert them to P(UP) by computing
the fraction of quantile mass above the current close price.

Install:
    pip install "chronos-forecasting>=2.0" torch

Usage:
    python3 test_chronos2.py [--candles 600] [--context 512] [--edge 0.05]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import torch

MODEL_DIR = Path(__file__).parent / "hf-models" / "chronos-2"


# ── Binance data ───────────────────────────────────────────────────────────────

def fetch_binance_5m(n: int = 1000) -> pd.DataFrame:
    print(f"Fetching {n} 5-min BTC/USDT candles from Binance …")
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "5m", "limit": n},
        timeout=30,
    )
    r.raise_for_status()
    cols = ["timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades",
            "taker_buy_vol", "taker_buy_quote_vol", "ignore"]
    df = pd.DataFrame(r.json(), columns=cols)
    df["timestamp"] = df["timestamp"].astype(int) // 1000
    df["close"] = df["close"].astype(float)
    return df[["timestamp", "close"]]


# ── Model ──────────────────────────────────────────────────────────────────────

QUANTILE_LEVELS = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]


def load_chronos2():
    print(f"Loading Chronos-2 from {MODEL_DIR} …")
    try:
        from chronos import Chronos2Pipeline
    except ImportError:
        print("ERROR: chronos-forecasting not installed.")
        print("  pip install 'chronos-forecasting>=2.0'")
        raise

    pipeline = Chronos2Pipeline.from_pretrained(
        str(MODEL_DIR),
        device_map="cpu",
        dtype=torch.float32,
    )
    print("  Loaded Chronos-2")
    return pipeline


# ── Backtest ───────────────────────────────────────────────────────────────────

def p_up_from_quantiles(quantile_vals: np.ndarray, current_close: float) -> float:
    """
    Given quantile values at QUANTILE_LEVELS and current close price,
    linearly interpolate to estimate P(next_close > current_close).
    """
    levels = np.array(QUANTILE_LEVELS)
    vals   = quantile_vals

    if current_close <= vals[0]:
        return 1.0
    if current_close >= vals[-1]:
        return 0.0

    # Find bracket
    idx = np.searchsorted(vals, current_close) - 1
    idx = int(np.clip(idx, 0, len(vals) - 2))

    # Linear interpolation within the bracket
    v_lo, v_hi = vals[idx], vals[idx + 1]
    q_lo, q_hi = levels[idx], levels[idx + 1]
    if v_hi == v_lo:
        q_at_current = (q_lo + q_hi) / 2
    else:
        frac = (current_close - v_lo) / (v_hi - v_lo)
        q_at_current = q_lo + frac * (q_hi - q_lo)

    return float(1.0 - q_at_current)


def run_backtest(df: pd.DataFrame, pipeline, context_len: int,
                 min_edge: float, batch_size: int = 64) -> pd.DataFrame:
    closes = df["close"].values.astype(np.float32)
    n = len(closes)
    indices = list(range(context_len, n - 1))
    print(f"Running backtest on {len(indices)} ticks (batch={batch_size}) …")

    records = []

    for batch_start in range(0, len(indices), batch_size):
        batch_idx = indices[batch_start: batch_start + batch_size]
        contexts = [
            torch.tensor(closes[i - context_len: i], dtype=torch.float32)
            for i in batch_idx
        ]

        # predict_quantiles(inputs, prediction_length, quantile_levels)
        # returns (quantile_forecasts, mean_forecasts)
        # quantile_forecasts shape: (batch, num_quantiles, prediction_length)
        q_forecasts, _ = pipeline.predict_quantiles(
            contexts,
            prediction_length=1,
            quantile_levels=QUANTILE_LEVELS,
        )

        # Normalise to numpy: handle tensor (B, Q, H), list of tensors, or ndarray
        if hasattr(q_forecasts, "cpu"):
            q_np = q_forecasts.cpu().numpy()          # (B, Q, H)
        elif isinstance(q_forecasts, list):
            q_np = np.stack([
                t.cpu().numpy() if hasattr(t, "cpu") else np.array(t)
                for t in q_forecasts
            ])                                         # (B, Q, H)
        else:
            q_np = np.array(q_forecasts)

        for k, i in enumerate(batch_idx):
            # Flatten to 1-D scalar quantile values regardless of shape returned
            raw = q_np[k]
            q_vals = np.array(raw, dtype=float).flatten()[:len(QUANTILE_LEVELS)]
            # Ensure each element is a Python float scalar
            q_vals = np.array([float(v) for v in q_vals])
            current_close = float(closes[i])
            p_up  = p_up_from_quantiles(q_vals, current_close)
            actual = int(closes[i + 1] >= current_close)
            edge   = abs(p_up - 0.5)
            pred   = int(p_up >= 0.5)
            ts = pd.to_datetime(df["timestamp"].iloc[i], unit="s", utc=True)
            records.append({
                "time":    ts.strftime("%H:%M"),
                "close":   current_close,
                "p_up":    p_up,
                "pred":    pred,
                "actual":  actual,
                "correct": int(pred == actual),
                "edge":    edge,
                "bet":     int(edge >= min_edge),
            })

        done = min(batch_start + batch_size, len(indices))
        print(f"  {done}/{len(indices)} ticks …", end="\r")

    print()
    return pd.DataFrame(records)


# ── Stats (same format as test_model.py) ──────────────────────────────────────

def print_stats(results: pd.DataFrame, min_edge: float) -> None:
    total  = len(results)
    bets   = results[results["bet"] == 1]
    n_bets = len(bets)

    acc_all = results["correct"].mean()
    acc_bet = bets["correct"].mean() if n_bets else float("nan")
    pnl     = (bets["correct"] * 2 - 1).sum() if n_bets else 0

    up_bets   = bets[bets["pred"] == 1]
    down_bets = bets[bets["pred"] == 0]
    up_won    = up_bets["correct"].mean()   if len(up_bets)   else float("nan")
    down_won  = down_bets["correct"].mean() if len(down_bets) else float("nan")

    print("\n" + "=" * 52)
    print(f"  Chronos-2 Backtest  ({total} × 5m candles ≈ {total * 5 // 60}h)")
    print("=" * 52)
    print(f"  Total ticks evaluated : {total}")
    print(f"  Ticks with edge≥{min_edge:.2f} : {n_bets}  ({n_bets/total*100:.1f}%)")
    print(f"  Accuracy (all ticks)  : {acc_all:.2%}")
    print(f"  Accuracy (bet ticks)  : {acc_bet:.2%}")
    print(f"  UP   bets won         : {up_won:.2%}  ({len(up_bets)} bets)")
    print(f"  DOWN bets won         : {down_won:.2%}  ({len(down_bets)} bets)")
    print(f"  Net units P&L (bets)  : {pnl:+.0f}  (@ $1/bet)")
    print("=" * 52)

    print("\n  Edge bucket breakdown:")
    print(f"  {'Edge ≥':>8}  {'Ticks':>6}  {'Accuracy':>9}  {'UP won':>8}  {'DOWN won':>9}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*9}")
    for thr in [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
        sub = results[results["edge"] >= thr]
        if not len(sub):
            continue
        s_up   = sub[sub["pred"] == 1]
        s_down = sub[sub["pred"] == 0]
        u = f"{s_up['correct'].mean():.2%}"   if len(s_up)   else "  n/a  "
        d = f"{s_down['correct'].mean():.2%}" if len(s_down) else "  n/a  "
        print(f"  {thr:>8.2f}  {len(sub):>6}  {sub['correct'].mean():>9.2%}  {u:>8}  {d:>9}")

    last = results.tail(30)
    print(f"\n  Last {len(last)} ticks:")
    print(f"  {'Time':>6}  {'Close':>9}  {'P(UP)':>6}  {'Pred':>5}  {'Actual':>6}  {'OK':>3}  {'Bet':>3}")
    print(f"  {'-'*6}  {'-'*9}  {'-'*6}  {'-'*5}  {'-'*6}  {'-'*3}  {'-'*3}")
    for _, row in last.iterrows():
        d = "UP  " if row["pred"] else "DOWN"
        a = "UP  " if row["actual"] else "DOWN"
        ok  = "✓" if row["correct"] else "✗"
        bet = "•" if row["bet"] else ""
        print(f"  {row['time']:>6}  {row['close']:>9.2f}  {row['p_up']:>6.3f}  {d}  {a}  {ok:>3}  {bet:>3}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", type=int,   default=700,  help="5m candles to fetch")
    parser.add_argument("--context", type=int,   default=512,  help="Lookback bars fed to model")
    parser.add_argument("--edge",    type=float, default=0.05, help="Min |P-0.5| to count as a bet")
    parser.add_argument("--batch",   type=int,   default=64,   help="Inference batch size")
    args = parser.parse_args()

    df       = fetch_binance_5m(args.candles)
    pipeline = load_chronos2()
    results  = run_backtest(df, pipeline, args.context, args.edge, args.batch)
    print_stats(results, args.edge)


if __name__ == "__main__":
    main()
