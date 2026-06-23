"""Phase-1 characterization (the GO/NO-GO): is the new-listing 'pump then bleed' real, and how big?

Backfills genuine new SPOT listings from the announcement feed, pulls each one's first trading day
of 1m closes from Binance (first kline = the open), computes per-listing metrics, and prints the
distribution. Survivorship-biased toward survivors (delisted dumpers are gone) — an UPPER bound.

Usage:  PYTHONPATH=src python3 scripts/characterize.py [--pages 6] [--out data/listings.parquet]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import pandas as pd

from listing_sniper.announcements import fetch_articles, parse_listing
from listing_sniper.dataset import first_day_closes, listing_metrics

_QUOTES = ("USDT", "FDUSD", "USDC")


def genuine_spot_listings(pages: int, page_size: int = 50) -> list:
    """New spot listings only: 'Binance Will List …' with exactly one ticker (drops Earn/Margin/
    JPY/bStocks/TradFi/notice noise)."""
    out, seen = [], set()
    for p in range(1, pages + 1):
        for art in fetch_articles(48, page_size, p):
            lst = parse_listing(art)
            if "will list" not in lst.title.lower() or len(lst.tickers) != 1:
                continue
            t = lst.tickers[0]
            if t in seen:
                continue
            seen.add(t)
            out.append(lst)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    listings = genuine_spot_listings(args.pages)
    print(f"genuine 'Will List' spot listings found: {len(listings)}  "
          f"(announcement pages={args.pages})")

    rows = []
    for lst in listings:
        for q in _QUOTES:
            open_ms, closes = first_day_closes(lst.tickers[0] + q, futures=False, minutes=1500)
            if closes:
                break
        m = listing_metrics(closes)
        if not m:
            continue
        m["ticker"] = lst.tickers[0]
        m["pair"] = lst.tickers[0] + q
        m["open_date"] = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc).date().isoformat()
        rows.append(m)

    if not rows:
        print("no klines resolved (symbols may be delisted/renamed)."); return 1
    df = pd.DataFrame(rows).sort_values("open_date")
    n = len(df)
    print(f"resolved klines for {n}/{len(listings)} listings\n")

    def med(c):
        return df[c].median()

    print("=== first-day pattern (medians across listings) ===")
    print(f"  peak_ret           {med('peak_ret'):+.1%}   (median time-to-peak {med('time_to_peak_min'):.0f} min)")
    print(f"  drawdown_from_peak {med('dd_from_peak'):+.1%}")
    print(f"  ret @ 15m / 1h / 24h: {med('ret_15m'):+.1%} / {med('ret_1h'):+.1%} / {med('ret_24h'):+.1%}")
    print(f"  end-of-day ret     {med('end_ret'):+.1%}")
    print(f"  'dumped from open' rate: {df['dumped_from_open'].mean():.0%}")
    print(f"  share red at 24h (ret_24h<0): {(df['ret_24h'] < 0).mean():.0%}")

    print("\n=== sample (most recent 12) ===")
    cols = ["open_date", "pair", "peak_ret", "time_to_peak_min", "ret_1h", "ret_24h", "dumped_from_open"]
    with pd.option_context("display.max_rows", 20, "display.width", 140):
        print(df[cols].tail(12).to_string(index=False,
              formatters={"peak_ret": "{:+.0%}".format, "ret_1h": "{:+.0%}".format,
                          "ret_24h": "{:+.0%}".format}))

    if args.out:
        df.to_parquet(args.out)
        print(f"\nsaved -> {args.out}")
    print("\n⚠ survivorship-biased (delisted dumpers excluded) -> treat as an upper bound. PLAN.md §4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
