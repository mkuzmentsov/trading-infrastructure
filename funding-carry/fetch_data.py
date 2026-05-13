"""Fetch historical funding rates + hourly prices from Hyperliquid.

The funding-carry strategy is: long Kraken spot + short Hyperliquid perp, to
collect HL's hourly funding. The dominant PnL term is Σ(hourly funding rate)
over the holding period, so the key data is HL's fundingHistory. We also pull
HL 1h candles per coin for a price series (used to size notional and, later,
to model the spot/perp basis — for v1 we approximate perp≈spot).

Hyperliquid info API: POST https://api.hyperliquid.xyz/info
  - {"type":"fundingHistory","coin":"BTC","startTime":<ms>,"endTime":<ms>}
      -> [{"coin","fundingRate","premium","time"}], hourly, ~500/req -> paginate
  - {"type":"candleSnapshot","req":{"coin":"BTC","interval":"1h","startTime":<ms>,"endTime":<ms>}}
      -> [{"t","T","s","o","h","l","c","v","n"}], ~5000/req

Usage: python3 funding-carry/fetch_data.py [--months 12] [--coins BTC,ETH,SOL,...]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import requests

HL_INFO = "https://api.hyperliquid.xyz/info"
REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "funding-carry" / "data"


def _post(body: dict, retries: int = 4) -> object:
    for i in range(retries):
        try:
            r = requests.post(HL_INFO, json=body, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return None


def fetch_funding(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginate fundingHistory; HL caps ~500 rows/req -> walk forward in time."""
    rows: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        chunk = _post({"type": "fundingHistory", "coin": coin,
                       "startTime": cur, "endTime": end_ms})
        if not chunk:
            break
        rows.extend(chunk)
        last_t = int(chunk[-1]["time"])
        if last_t <= cur or len(chunk) < 2:
            break
        cur = last_t + 1
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["coin", "time", "fundingRate", "premium"])
    df = pd.DataFrame(rows)
    df["time"] = df["time"].astype("int64")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def fetch_candles(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """1h candles; HL caps ~5000/req -> walk forward."""
    rows: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        chunk = _post({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": "1h",
                               "startTime": cur, "endTime": end_ms}})
        if not chunk:
            break
        rows.extend(chunk)
        last_T = int(chunk[-1]["T"])
        if last_T <= cur or len(chunk) < 2:
            break
        cur = last_T + 1
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame(columns=["coin", "time", "open", "high", "low", "close", "vol"])
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "vol"})
    df["coin"] = coin
    df["time"] = df["time"].astype("int64")
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = df[c].astype(float)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df[["coin", "time", "dt", "open", "high", "low", "close", "vol"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=float, default=12.0)
    ap.add_argument("--coins", default="BTC,ETH,SOL,HYPE,DOGE,XRP,AVAX,LINK")
    args = ap.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(args.months * 30 * 24 * 3600 * 1000)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fund_frames, cdl_frames = [], []
    for coin in coins:
        try:
            f = fetch_funding(coin, start_ms, now_ms)
            c = fetch_candles(coin, start_ms, now_ms)
        except Exception as e:  # noqa: BLE001
            print(f"  {coin}: FAILED ({e}) — skipping")
            continue
        if len(f):
            ann = f["fundingRate"].mean() * 24 * 365 * 100
            print(f"  {coin}: {len(f)} funding hrs ({f['dt'].iloc[0].date()}→{f['dt'].iloc[-1].date()}), "
                  f"mean hourly={f['fundingRate'].mean()*1e4:.3f}bps  ~{ann:+.1f}%/yr;  {len(c)} candles")
            fund_frames.append(f)
            cdl_frames.append(c)
        else:
            print(f"  {coin}: no funding data")
        time.sleep(0.3)

    if not fund_frames:
        raise SystemExit("no data fetched")
    fund = pd.concat(fund_frames, ignore_index=True)
    cdl = pd.concat(cdl_frames, ignore_index=True)
    fund.to_parquet(DATA_DIR / "hl_funding.parquet", index=False)
    cdl.to_parquet(DATA_DIR / "hl_candles_1h.parquet", index=False)
    print(f"\n[fetch] wrote {DATA_DIR/'hl_funding.parquet'} ({len(fund)} rows)")
    print(f"[fetch] wrote {DATA_DIR/'hl_candles_1h.parquet'} ({len(cdl)} rows)")


if __name__ == "__main__":
    main()
