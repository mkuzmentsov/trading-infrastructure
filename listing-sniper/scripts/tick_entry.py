"""Sub-second entry test for the new-listing LONG lottery (the queued next step).

The 1-min-close analysis showed the +100% moves happen in the first SECONDS, before any retail-observable
price. This tests entry on the actual TICK path (perp aggTrades from data.binance.vision) at increasing
LATENCY delays, and runs the real path-dependent +100%/-50% bracket. The question: does catching the
first ticks make the long +EV, and how fast does the edge decay with latency?

For each perp listing: download um aggTrades for the open_date (first trade = the listing's first-ever
trade), slice the first WINDOW minutes, then for each entry delay measure:
  - entry price (first trade at/after the delay),
  - peak return over the remaining window,
  - bracket outcome: does price hit entry*2.0 (TP +100%) before entry*0.5 (SL -50%)?
Download is in-memory and discarded (peak disk ~one file). Honest bound: entry at a delay's first trade
is OPTIMISTIC (assumes you fill at that print; a real market order fills worse into the thin early book).

Usage:  python scripts/tick_entry.py [--tickers TRUMP APE ...] [--window-min 120]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile

import numpy as np
import pandas as pd

ROOT = "https://data.binance.vision/data/futures/um/daily/aggTrades"
COLS = ["agg_id", "price", "qty", "first_id", "last_id", "transact_time", "is_buyer_maker"]
DELAYS_S = [0, 5, 30, 60, 300]      # entry latency: first trade, 5s, 30s, 60s, 5min(≈1m-close proxy)
TP, SL = 2.0, 0.5                   # +100% take-profit, -50% stop (×entry price)


def fetch_aggtrades(pair: str, date: str, window_min: int):
    url = f"{ROOT}/{pair}/{pair}-aggTrades-{date}.zip"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ls-tick"}),
                                    timeout=60) as r:
            blob = r.read()
    except Exception as e:
        return None if "404" in str(e) else (_ for _ in ()).throw(e)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()
    skip = 1 if raw.lstrip().lower().startswith("agg") else 0
    df = pd.read_csv(io.StringIO(raw), header=None, names=COLS, skiprows=skip,
                     usecols=["price", "transact_time"])
    t0 = df["transact_time"].iloc[0]                          # first-ever trade
    df = df[df["transact_time"] <= t0 + window_min * 60_000]  # first WINDOW minutes
    return df["price"].to_numpy(float), (df["transact_time"].to_numpy() - t0) / 1000.0  # price, secs-from-open


def analyze(price, secs):
    out = {}
    for d in DELAYS_S:
        i0 = int(np.searchsorted(secs, d))                   # first trade at/after the delay
        if i0 >= len(price):
            out[d] = None; continue
        E = price[i0]
        path = price[i0:]
        peak = float(path.max() / E - 1.0)
        hit_tp = np.where(path >= E * TP)[0]
        hit_sl = np.where(path <= E * SL)[0]
        tp_i = hit_tp[0] if len(hit_tp) else np.inf
        sl_i = hit_sl[0] if len(hit_sl) else np.inf
        if tp_i < sl_i:
            bracket = TP - 1.0                               # +100%
        elif sl_i < tp_i:
            bracket = SL - 1.0                               # -50%
        else:
            bracket = float(path[-1] / E - 1.0)              # neither hit → exit at window end
        out[d] = {"entry": E, "peak": peak, "bracket": bracket,
                  "hit_tp": bool(np.isfinite(tp_i)), "hit_sl": bool(np.isfinite(sl_i))}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", default=None, help="subset by ticker (default: all perp listings)")
    ap.add_argument("--window-min", type=int, default=120)
    ap.add_argument("--out", default="data/tick_entry.parquet")
    args = ap.parse_args()
    lst = pd.read_parquet("data/listings.parquet")
    lst = lst[lst["has_perp"]].copy()
    if args.tickers:
        lst = lst[lst["ticker"].isin(args.tickers)]

    rows = []
    for _, r in lst.iterrows():
        res = fetch_aggtrades(r["pair"], r["open_date"], args.window_min)
        if res is None:
            print(f"{r['ticker']:>8} {r['open_date']}  no aggTrades (404)", flush=True); continue
        price, secs = res
        a = analyze(price, secs)
        d0, d300 = a.get(0), a.get(300)
        if d0:
            print(f"{r['ticker']:>8} {r['open_date']}  trades {len(price):>7}  "
                  f"first-tick peak {d0['peak']:>+7.1%} bracket {d0['bracket']:>+6.0%} | "
                  f"5m-entry peak {(d300['peak'] if d300 else float('nan')):>+7.1%}", flush=True)
        for d, v in a.items():
            if v:
                rows.append({"ticker": r["ticker"], "open_date": r["open_date"], "delay_s": d, **v})
    df = pd.DataFrame(rows)
    df.to_parquet(args.out, index=False)
    print(f"\nsaved {len(df)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
