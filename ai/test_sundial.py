"""
Backtest Sundial (128M) on BTC 5m direction prediction.

Sundial is a generative time series foundation model — it produces N random
samples of the future.  We run it zero-shot: feed the last CONTEXT_LEN close
prices, ask for 1 bar ahead, and compute P(UP) as the fraction of samples
where the predicted next close > current close.

Install:
    pip install transformers==4.40.1 torch

Usage:
    python3 test_sundial.py [--candles 600] [--context 512] [--samples 50] [--edge 0.05]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import torch

MODEL_DIR = Path(__file__).parent / "hf-models" / "sundial"
WARMUP = 0   # no indicator warmup needed — raw prices only


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

def load_sundial():
    print(f"Loading Sundial from {MODEL_DIR} …")
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_DIR), trust_remote_code=True
    )
    model.eval()
    print(f"  Loaded  ({sum(p.numel() for p in model.parameters()) / 1e6:.0f}M params)")
    return model


# ── Backtest ───────────────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, model, context_len: int,
                 num_samples: int, min_edge: float,
                 batch_size: int = 32) -> pd.DataFrame:
    closes = df["close"].values.astype(np.float32)
    n = len(closes)

    records = []
    indices = list(range(context_len, n - 1))
    print(f"Running backtest on {len(indices)} ticks (batch={batch_size}) …")

    for batch_start in range(0, len(indices), batch_size):
        batch_idx = indices[batch_start: batch_start + batch_size]

        # Build context windows — normalise each to mean≈0 std≈1 for stable flow matching
        windows, scales = [], []
        for i in batch_idx:
            w = closes[i - context_len: i].copy()
            mu, sigma = w.mean(), w.std() + 1e-8
            windows.append((w - mu) / sigma)
            scales.append((mu, sigma))

        seqs = torch.tensor(np.stack(windows), dtype=torch.float32)  # (B, context_len)

        with torch.no_grad():
            # output shape: (B, num_samples, forecast_len=1)
            output = model.generate(seqs, max_new_tokens=1, num_samples=num_samples)

        if output.dim() == 2:          # (B, num_samples) — squeeze if needed
            output = output.unsqueeze(-1)

        for k, i in enumerate(batch_idx):
            mu, sigma = scales[k]
            # De-normalise samples → absolute price
            samples_next = output[k, :, 0].cpu().numpy() * sigma + mu
            current_close = closes[i]
            p_up = float((samples_next > current_close).mean())
            actual = int(closes[i + 1] >= current_close)
            edge = abs(p_up - 0.5)
            pred = int(p_up >= 0.5)
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
    print(f"  Sundial Backtest  ({total} × 5m candles ≈ {total * 5 // 60}h)")
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
    parser.add_argument("--candles",  type=int,   default=700,   help="5m candles to fetch")
    parser.add_argument("--context",  type=int,   default=512,   help="Lookback bars fed to model")
    parser.add_argument("--samples",  type=int,   default=50,    help="Generated samples per tick")
    parser.add_argument("--edge",     type=float, default=0.05,  help="Min |P-0.5| to count as a bet")
    parser.add_argument("--batch",    type=int,   default=32,    help="Inference batch size")
    args = parser.parse_args()

    df    = fetch_binance_5m(args.candles)
    model = load_sundial()
    results = run_backtest(df, model, args.context, args.samples, args.edge, args.batch)
    print_stats(results, args.edge)


if __name__ == "__main__":
    main()
