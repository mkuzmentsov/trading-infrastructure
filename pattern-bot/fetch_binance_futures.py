"""Fetch Binance USDⓈ-M futures non-price data from data.binance.vision:
  - fundingRate         -> data/<SYM>_funding.parquet    [time, funding_rate]
  - premiumIndexKlines  -> data/<SYM>_premium_<iv>.parquet [time, premium]  (perp-vs-index basis)

These are the non-price inputs (positioning / funding / basis) we want as ML
features — the one signal class with prior evidence of a real edge.

Usage: python3 pattern-bot/fetch_binance_futures.py --symbol BTCUSDT --interval 1h --start 2019-09 --end 2026-05
"""
from __future__ import annotations
import argparse, io, time, zipfile
from pathlib import Path
import pandas as pd, requests

BASE = "https://data.binance.vision/data/futures/um/monthly"
DATA = Path(__file__).resolve().parent / "data"


def _months(start, end):
    sy, sm = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _csv(url):
    for a in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status(); break
        except Exception:
            if a == 2:
                raise
            time.sleep(1.5 * (a + 1))
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None)
    if not str(df.iloc[0, 0]).replace(".", "", 1).replace("-", "", 1).isdigit():
        df = df.iloc[1:].reset_index(drop=True)
    return df


def _norm_time(s):
    s = s.astype("int64")
    return (s // 1000) if s.iloc[0] > 1e14 else s   # microseconds → ms


def fetch_funding(sym, start, end):
    frames = []
    for y, m in _months(start, end):
        d = _csv(f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{y:04d}-{m:02d}.zip")
        if d is None or d.empty:
            continue
        d = d.iloc[:, [0, -1]].copy()       # calc_time, ..., last_funding_rate
        d.columns = ["time", "funding_rate"]
        d["time"] = _norm_time(d["time"]); d["funding_rate"] = d["funding_rate"].astype(float)
        frames.append(d)
    out = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time")
    p = DATA / f"{sym}_funding.parquet"; out.to_parquet(p, index=False)
    print(f"  funding: {len(out)} rows {pd.to_datetime(out['time'].iloc[0],unit='ms').date()}→"
          f"{pd.to_datetime(out['time'].iloc[-1],unit='ms').date()} -> {p.name}")


def fetch_premium(sym, interval, start, end):
    frames = []
    for y, m in _months(start, end):
        d = _csv(f"{BASE}/premiumIndexKlines/{sym}/{interval}/{sym}-{interval}-{y:04d}-{m:02d}.zip")
        if d is None or d.empty:
            continue
        d = d.iloc[:, [0, 4]].copy()        # open_time, close (= premium index)
        d.columns = ["time", "premium"]
        d["time"] = _norm_time(d["time"]); d["premium"] = d["premium"].astype(float)
        frames.append(d)
    out = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time")
    p = DATA / f"{sym}_premium_{interval}.parquet"; out.to_parquet(p, index=False)
    print(f"  premium: {len(out)} rows -> {p.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2019-09")
    ap.add_argument("--end", default="2026-05")
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"[futures] {a.symbol} {a.start}→{a.end}")
    fetch_funding(a.symbol, a.start, a.end)
    fetch_premium(a.symbol, a.interval, a.start, a.end)


if __name__ == "__main__":
    main()
