"""Build the per-listing dataset (one network pass) -> parquet, for offline analysis.

For each genuine 'Binance Will List' token: spot + perp first-day metrics, the perp-vs-spot listing
lag (our Binance-only proxy for 'was it already priced'), and the funding a short collects/pays over
the first 24h. Analysis (characterize.py) reads the parquet — no re-fetching.

Usage:  PYTHONPATH=src python3 scripts/build_dataset.py [--pages 24] [--out data/listings.parquet]
⚠ survivorship-biased (delisted names purged from Binance). PLAN.md §4.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import pandas as pd

from listing_sniper.announcements import new_spot_listings
from listing_sniper.dataset import (
    binance_funding,
    cumulative_funding,
    first_day_closes,
    listing_metrics,
)

_QUOTES = ("USDT", "FDUSD", "USDC")
_KEEP = ("peak_ret", "time_to_peak_min", "dd_from_peak", "ret_1h", "ret_24h", "end_ret", "dumped_from_open")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=24)
    ap.add_argument("--out", default="data/listings.parquet")
    args = ap.parse_args()

    listings = new_spot_listings(args.pages)
    print(f"genuine 'Will List' listings: {len(listings)} (pages={args.pages}) — fetching klines…")

    rows = []
    for i, lst in enumerate(listings, 1):
        tk = lst.tickers[0]
        s_ms, s_closes, pair = None, [], ""
        for q in _QUOTES:
            s_ms, s_closes = first_day_closes(tk + q, futures=False, minutes=1500)
            if s_closes:
                pair = tk + q
                break
        if not s_closes:
            continue
        p_ms, p_closes = first_day_closes(tk + "USDT", futures=True, minutes=1500)
        rec = {
            "ticker": tk, "pair": pair,
            "open_date": datetime.fromtimestamp(s_ms / 1000, tz=timezone.utc).date().isoformat(),
            "has_perp": bool(p_closes),
            "lag_min": ((p_ms - s_ms) / 60_000) if (p_ms and s_ms) else None,
        }
        for k in _KEEP:
            rec[f"spot_{k}"] = listing_metrics(s_closes).get(k)
        if p_closes:
            pm = listing_metrics(p_closes)
            for k in _KEEP:
                rec[f"perp_{k}"] = pm.get(k)
            fr = binance_funding(tk + "USDT", start_ms=p_ms, limit=24)
            rec["short_funding_24h"] = cumulative_funding(r["fundingRate"] for r in fr) if fr else 0.0
        rows.append(rec)
        if i % 10 == 0:
            print(f"  …{i}/{len(listings)}")

    df = pd.DataFrame(rows).sort_values("open_date")
    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df.to_parquet(args.out)
    print(f"saved {len(df)} listings -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
