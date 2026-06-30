"""Bulk-fetch long-history klines from data.binance.vision into the project's bar store.

The exchange REST API paginates slowly for years of 5m/15m data; data.binance.vision ships monthly
CSV zips that are far faster. This downloads spot BTCUSDT klines for a set of intervals over a month
range, normalizes to the store schema, and writes one parquet per interval under a chosen venue tag
(default ``bvision`` — kept SEPARATE from the existing ``binance`` files so nothing is clobbered).

Usage:
  PYTHONPATH=src python3 scripts/fetch_binance_vision.py --intervals 5m 15m 1h \
      --start 2022-01 --end 2026-05 [--symbol BTCUSDT --base BTC --venue bvision]
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request

import pandas as pd

ROOT = "https://data.binance.vision/data"
# kline / markPriceKline CSV columns (12-col; newer files carry a header row we detect + skip)
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "count", "tb_base", "tb_quote", "ignore"]


def months(start: str, end: str):
    s = pd.Period(start, "M"); e = pd.Period(end, "M")
    p = s
    while p <= e:
        yield f"{p.year:04d}-{p.month:02d}"
        p += 1


def _to_ms(series: pd.Series) -> pd.Series:
    """Binance switched some 2025+ files to microseconds; normalize anything to ms."""
    v = series.astype("int64")
    # >1e15 ≈ microseconds (16 digits); 1e12–1e15 ≈ ms (13 digits)
    return (v // 1000).where(v > 1_000_000_000_000_000, v)


def fetch_month(symbol: str, interval: str, ym: str, *, market: str, kind: str) -> pd.DataFrame | None:
    seg = "spot" if market == "spot" else f"futures/{market}"   # um/cm live under futures/
    url = f"{ROOT}/{seg}/monthly/{kind}/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
    try:
        with urlopen(Request(url, headers={"User-Agent": "atb-fetch"}), timeout=60) as r:
            blob = r.read()
    except Exception as e:                       # 404 = month not published yet; skip
        if "404" in str(e):
            return None
        raise
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()
    # newer files may include a header row starting with "open_time"
    skip = 1 if raw.lstrip().lower().startswith("open_time") else 0
    df = pd.read_csv(io.StringIO(raw), header=None, names=COLS, skiprows=skip)
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intervals", nargs="+", default=["5m", "15m", "1h"])
    ap.add_argument("--start", default="2022-01")
    ap.add_argument("--end", default="2026-05")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--base", default="BTC")
    ap.add_argument("--venue", default="bvision")
    ap.add_argument("--market", default="spot", choices=["spot", "um", "cm"],
                    help="spot, or um/cm USDT-/COIN-margined futures")
    ap.add_argument("--kind", default="klines", choices=["klines", "markPriceKlines", "premiumIndexKlines"])
    ap.add_argument("--data-dir", default="./data")
    args = ap.parse_args()

    out_dir = f"{args.data_dir}/bars"
    ml = list(months(args.start, args.end))
    for interval in args.intervals:
        print(f"[{interval}] downloading {len(ml)} months {args.start}…{args.end} …", flush=True)
        frames: dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=12) as ex:
            futs = {ex.submit(fetch_month, args.symbol, interval, ym,
                              market=args.market, kind=args.kind): ym for ym in ml}
            for f in as_completed(futs):
                d = f.result()
                if d is not None:
                    frames[futs[f]] = d
        if not frames:
            print(f"  !! no data for {interval}"); continue
        df = pd.concat([frames[ym] for ym in ml if ym in frames], ignore_index=True)
        ts = pd.to_datetime(_to_ms(df["open_time"]), unit="ms", utc=True)
        kn = pd.to_datetime(_to_ms(df["close_time"]), unit="ms", utc=True)
        out = pd.DataFrame({
            "symbol": args.base, "venue": args.venue, "ts": ts,
            "open": df["open"].astype(float), "high": df["high"].astype(float),
            "low": df["low"].astype(float), "close": df["close"].astype(float),
            "volume": df["volume"].astype(float), "knowable_at": kn,
        }).drop_duplicates(subset=["ts"], keep="last").sort_values("ts").reset_index(drop=True)
        path = f"{out_dir}/{args.venue}__{args.base}__{interval}.parquet"
        out.to_parquet(path, index=False)
        print(f"  wrote {path}  {len(out):,} bars  {out['ts'].iloc[0]} → {out['ts'].iloc[-1]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
