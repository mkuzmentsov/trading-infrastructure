"""Download historical klines from Binance's public data dump (data.binance.vision)
and build a backtest dataset in our parquet format.

Binance publishes monthly kline zips at:
  https://data.binance.vision/data/spot/monthly/klines/<SYMBOL>/<INTERVAL>/<SYMBOL>-<INTERVAL>-YYYY-MM.zip
Each zip holds a headerless CSV: open_time, open, high, low, close, volume, ...
(open_time is ms historically, microseconds in newer files — normalized here.)

This gives a MUCH longer history than the Hyperliquid candle cap (~5000 bars),
so it's our out-of-sample / multi-regime validation set.

Usage:
    python3 pattern-bot/fetch_binance.py [--symbol BTCUSDT] [--interval 1h]
        [--start 2018-01] [--end 2026-05]

Writes pattern-bot/data/<SYMBOL>_<interval>.parquet
"""
from __future__ import annotations

import argparse
import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.binance.vision/data/spot/monthly/klines"
DATA_DIR = Path(__file__).resolve().parent / "data"


def _months(start: str, end: str):
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def fetch_month(symbol: str, interval: str, y: int, m: int) -> pd.DataFrame | None:
    url = f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{y:04d}-{m:02d}.zip"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None)
    # Drop a header row if the file has one (newer dumps do).
    if not str(df.iloc[0, 0]).replace(".", "", 1).isdigit():
        df = df.iloc[1:].reset_index(drop=True)
    df = df.iloc[:, :6].copy()
    df.columns = ["time", "open", "high", "low", "close", "vol"]
    df["time"] = df["time"].astype("int64")
    if df["time"].iloc[0] > 1e14:          # microseconds → milliseconds
        df["time"] = df["time"] // 1000
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = df[c].astype(float)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2018-01", help="YYYY-MM")
    ap.add_argument("--end", default="2026-05", help="YYYY-MM")
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[binance] {args.symbol} {args.interval}  {args.start} → {args.end}")
    frames, got, missing = [], 0, 0
    for y, m in _months(args.start, args.end):
        try:
            d = fetch_month(args.symbol, args.interval, y, m)
        except Exception as e:  # noqa: BLE001
            print(f"  {y}-{m:02d}: FAILED ({e})")
            continue
        if d is None or d.empty:
            missing += 1
            continue
        frames.append(d)
        got += 1
        if got % 12 == 0:
            print(f"  …{y}-{m:02d}  ({got} months, {sum(len(f) for f in frames)} candles)")
        time.sleep(0.05)

    if not frames:
        raise SystemExit("no data fetched (check symbol/interval/date range)")
    df = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    out = DATA_DIR / f"{args.symbol}_{args.interval}.parquet"
    df.to_parquet(out, index=False)
    print(f"[binance] {got} months ({missing} missing), {len(df)} candles "
          f"{df['dt'].iloc[0].date()} → {df['dt'].iloc[-1].date()}  -> {out.name}")


if __name__ == "__main__":
    main()
