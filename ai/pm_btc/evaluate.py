"""Hypothetical-PnL evaluation: replay the dataset snapshot-by-snapshot, take
the first tradable signal per bar, and compare the trained ML model against the
current closed-form signal (from `signal.debug.p_up` logged in the snapshot).

This is not a full backtest — it assumes entry fills at the ask and no exits
other than bar-end resolution (win = +1*(1-price), lose = -1*price). It's a
directional check on whether the ML model would pick better entries than the
current signal.

Usage:
    python evaluate.py --dataset outputs/pm_btc_dataset.parquet \\
        --model outputs/pm_btc_model.txt --min-edge 0.05
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from features import FEATURE_COLUMNS  # noqa: E402

try:
    import lightgbm as lgb
except ImportError as e:
    raise SystemExit("lightgbm required") from e


def evaluate(df: pd.DataFrame, model_path: str, min_edge: float, min_price: float, max_price: float) -> dict:
    booster = lgb.Booster(model_file=model_path)
    X = df[FEATURE_COLUMNS].values
    df = df.copy()
    df["p_up_ml"] = booster.predict(X)
    # Sort within each bar by time so "first tradable tick" is reproducible.
    df.sort_values(["condition_id", "ts"], inplace=True)

    def simulate(pred_col: str) -> dict:
        entries = []
        # Group by bar, take the first row where edge on either side >= min_edge
        # and the target ask is within [min_price, max_price].
        for cid, grp in df.groupby("condition_id", sort=False):
            label = int(grp["y"].iloc[0])
            for _, row in grp.iterrows():
                p_up = float(row[pred_col])
                up_ask = float(row["up_ask"])
                down_ask = float(row["down_ask"])
                edge_up = p_up - up_ask
                edge_dn = (1.0 - p_up) - down_ask
                # Pick the better side that's also tradable within the band.
                options = []
                if min_price <= up_ask <= max_price and edge_up >= min_edge:
                    options.append(("UP", up_ask, edge_up, 1 if label == 1 else 0))
                if min_price <= down_ask <= max_price and edge_dn >= min_edge:
                    options.append(("DOWN", down_ask, edge_dn, 1 if label == 0 else 0))
                if not options:
                    continue
                options.sort(key=lambda t: -t[2])  # highest edge first
                side, price, edge, won = options[0]
                pnl_per_share = (1.0 - price) if won else -price
                entries.append({
                    "condition_id": cid,
                    "side": side,
                    "price": price,
                    "edge": edge,
                    "won": won,
                    "pnl_per_share": pnl_per_share,
                    "bar_resolved_up": label,
                })
                break  # one entry per bar
        if not entries:
            return {"n_entries": 0, "note": f"no entries at min_edge={min_edge}"}
        e_df = pd.DataFrame(entries)
        return {
            "n_entries": int(len(e_df)),
            "hit_rate": float(e_df["won"].mean()),
            "avg_edge": float(e_df["edge"].mean()),
            "avg_price": float(e_df["price"].mean()),
            "avg_pnl_per_share": float(e_df["pnl_per_share"].mean()),
            "total_pnl_per_share": float(e_df["pnl_per_share"].sum()),
            "side_split": {k: int(v) for k, v in e_df["side"].value_counts().items()},
        }

    # Closed-form baseline: signal.debug.p_up was logged per snapshot, but we
    # don't have it in our feature table. Use the implied-from-book proxy as a
    # stand-in "market" baseline for comparison.
    df["p_up_market"] = df["implied_p_up_from_book"]

    out = {
        "min_edge": min_edge,
        "min_price": min_price,
        "max_price": max_price,
        "ml_model": simulate("p_up_ml"),
        "market_implied_baseline": simulate("p_up_market"),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--min-edge", type=float, default=0.05)
    ap.add_argument("--min-price", type=float, default=0.15)
    ap.add_argument("--max-price", type=float, default=0.40)
    args = ap.parse_args()

    df = pd.read_parquet(args.dataset)
    res = evaluate(df, args.model, args.min_edge, args.min_price, args.max_price)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
