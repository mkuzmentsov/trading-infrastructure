"""Fetch historical OHLC candles from Hyperliquid for the pattern bot.

The double-top/bottom detector runs on OHLC candles, so the only data we need is
a price series per coin. We pull it from the same public HL info API the live bot
uses for its candles, so backtest and live agree on the data source.

Hyperliquid info API: POST https://api.hyperliquid.xyz/info
  {"type":"candleSnapshot","req":{"coin":"BTC","interval":"1h","startTime":<ms>,"endTime":<ms>}}
    -> [{"t","T","s","o","h","l","c","v","n"}], ~5000 candles/req -> paginate

Usage:
    python3 pattern-bot/fetch_data.py [--coins BTC,ETH,SOL] [--interval 1h] [--months 12]

Writes one parquet per coin: pattern-bot/data/<COIN>_<interval>.parquet
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

HL_INFO = "https://api.hyperliquid.xyz/info"
DATA_DIR = Path(__file__).resolve().parent / "data"

# Approximate ms per candle, used only to size pagination steps.
_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}


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


def fetch_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paginate candleSnapshot (HL caps ~5000/req) walking forward in time."""
    rows: list[dict] = []
    cur = start_ms
    while cur < end_ms:
        chunk = _post({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": interval,
                               "startTime": cur, "endTime": end_ms}})
        if not chunk:
            break
        rows.extend(chunk)
        last_T = int(chunk[-1]["T"])
        if last_T <= cur or len(chunk) < 2:
            break
        cur = last_T + 1
        time.sleep(0.15)
    cols = ["coin", "time", "dt", "open", "high", "low", "close", "vol"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows).rename(columns={"t": "time", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "vol"})
    df["coin"] = coin
    df["time"] = df["time"].astype("int64")
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = df[c].astype(float)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df[cols]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC,ETH,SOL")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--months", type=float, default=12.0)
    args = ap.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    if args.interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported interval {args.interval!r}; pick one of {list(_INTERVAL_MS)}")

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(args.months * 30 * 24 * 3600 * 1000)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[fetch] {coins} interval={args.interval} months={args.months}")
    for coin in coins:
        try:
            c = fetch_candles(coin, args.interval, start_ms, now_ms)
        except Exception as e:  # noqa: BLE001
            print(f"  {coin}: FAILED ({e}) — skipping")
            continue
        if not len(c):
            print(f"  {coin}: no candle data")
            continue
        out = DATA_DIR / f"{coin}_{args.interval}.parquet"
        c.to_parquet(out, index=False)
        print(f"  {coin}: {len(c)} candles {c['dt'].iloc[0].date()}→{c['dt'].iloc[-1].date()} "
              f"-> {out.name}")
        time.sleep(0.3)
    print(f"[fetch] done -> {DATA_DIR}")


if __name__ == "__main__":
    main()
