"""Characterize the listing dataset (reads the parquet from build_dataset.py — no network).

The headline split: GENUINELY-NEW listings (spot+perp within ~1h = real price discovery) vs
CONTINUATIONS (perp already traded days earlier). The naive 'all listings' stats conflate them.

Usage:  PYTHONPATH=src python3 scripts/characterize.py [--data data/listings.parquet]
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd


def _block(df: pd.DataFrame, label: str) -> None:
    n = len(df)
    if n == 0:
        print(f"\n[{label}] (none)"); return
    print(f"\n[{label}]  n={n}")
    print(f"  spot: peak {df['spot_peak_ret'].median():+.0%} | ret@24h {df['spot_ret_24h'].median():+.1%} | "
          f"red@24h {(df['spot_ret_24h'] < 0).mean():.0%} | dumped-from-open {df['spot_dumped_from_open'].mean():.0%}")
    perp = df[df["has_perp"]]
    if len(perp):
        print(f"  perp: peak {perp['perp_peak_ret'].median():+.0%} | ret@24h {perp['perp_ret_24h'].median():+.1%} | "
              f"red@24h {(perp['perp_ret_24h'] < 0).mean():.0%}")
        print(f"  short funding/24h: median {perp['short_funding_24h'].median():+.2%} | "
              f"pays-short {(perp['short_funding_24h'] > 0).mean():.0%} | worst {perp['short_funding_24h'].min():+.1%}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/listings.parquet")
    ap.add_argument("--new-lag-min", type=float, default=60.0, help="|lag| <= this = genuinely-new")
    args = ap.parse_args()

    df = pd.read_parquet(args.data)
    print(f"listings: {len(df)}  ({df['open_date'].min()} → {df['open_date'].max()})  "
          f"with perp: {df['has_perp'].mean():.0%}")

    lag = df["lag_min"].abs()
    new = df[df["has_perp"] & (lag <= args.new_lag_min)]
    cont = df[df["has_perp"] & (lag > args.new_lag_min)]
    _block(df, "ALL listings (conflated — don't trust this one)")
    _block(new, f"GENUINELY-NEW (spot+perp within {args.new_lag_min:.0f}m)")
    _block(cont, "CONTINUATION (perp predates spot)")

    print("\n=== genuinely-new sample ===")
    cols = ["open_date", "pair", "lag_min", "perp_peak_ret", "perp_ret_24h", "short_funding_24h"]
    with pd.option_context("display.width", 130):
        print(new[cols].to_string(index=False, formatters={
            "perp_peak_ret": "{:+.0%}".format, "perp_ret_24h": "{:+.0%}".format,
            "short_funding_24h": "{:+.2%}".format, "lag_min": "{:.0f}".format}))
    print("\n⚠ survivorship-biased (delisted dumpers gone). PLAN.md §4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
