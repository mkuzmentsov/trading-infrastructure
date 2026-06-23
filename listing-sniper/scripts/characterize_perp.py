"""Phase-2 input: can we actually SHORT the listing, and what does the perp + funding look like?

For each genuine 'Will List' token, checks the USDⓈ-M perp: is there one, when did it list vs spot,
how did the perp itself behave on day one, and — critically — what funding a constant short
collected/paid over the first 24h. This is what decides whether the downward-drift bias from
characterize.py is *tradeable*.

Usage:  PYTHONPATH=src python3 scripts/characterize_perp.py [--pages 12]
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from listing_sniper.announcements import new_spot_listings
from listing_sniper.dataset import (
    binance_funding,
    cumulative_funding,
    first_day_closes,
    listing_metrics,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=12)
    args = ap.parse_args()

    listings = new_spot_listings(args.pages)
    rows = []
    for lst in listings:
        tk = lst.tickers[0]
        spot_ms, _ = first_day_closes(tk + "USDT", futures=False, minutes=2)   # just the open ts
        perp_ms, perp_closes = first_day_closes(tk + "USDT", futures=True, minutes=1500)
        has_perp = bool(perp_closes)
        rec = {"ticker": tk, "has_perp": has_perp}
        if has_perp:
            m = listing_metrics(perp_closes)
            rec.update(perp_peak_ret=m.get("peak_ret"), perp_dd=m.get("dd_from_peak"),
                       perp_ret_1h=m.get("ret_1h"), perp_ret_24h=m.get("ret_24h"))
            # perp-vs-spot listing lag (minutes); >0 means perp listed AFTER spot
            rec["perp_lag_min"] = (perp_ms - spot_ms) / 60_000 if (perp_ms and spot_ms) else None
            # funding a SHORT earns(+)/pays(-) over the first ~24h
            fr = binance_funding(tk + "USDT", start_ms=perp_ms, limit=24)
            rec["n_funding"] = len(fr)
            rec["short_funding_24h"] = cumulative_funding(r["fundingRate"] for r in fr) if fr else 0.0
        rows.append(rec)

    df = pd.DataFrame(rows)
    n = len(df)
    perp = df[df["has_perp"]]
    print(f"listings checked: {n}   with a USDⓈ-M perp: {len(perp)} ({len(perp)/max(n,1):.0%})\n")
    if perp.empty:
        print("no perps resolved."); return 1

    def med(c):
        return perp[c].median()

    print("=== the perp (the side we'd actually short) — medians ===")
    print(f"  perp peak_ret            {med('perp_peak_ret'):+.1%}")
    print(f"  perp drawdown_from_peak  {med('perp_dd'):+.1%}")
    print(f"  perp ret @ 1h / 24h      {med('perp_ret_1h'):+.1%} / {med('perp_ret_24h'):+.1%}")
    print(f"  perp red @ 24h           {(perp['perp_ret_24h'] < 0).mean():.0%}")
    print(f"  perp-vs-spot listing lag {med('perp_lag_min'):+.0f} min  "
          f"(perp listed same-time as spot: {(perp['perp_lag_min'].abs() <= 5).mean():.0%})")
    print("\n=== funding to a SHORT over first ~24h (>0 = short is PAID to hold) ===")
    print(f"  median short funding     {med('short_funding_24h'):+.3%}")
    print(f"  short PAID (funding>0):  {(perp['short_funding_24h'] > 0).mean():.0%} of perps")
    print(f"  worst (short pays most): {perp['short_funding_24h'].min():+.3%}")

    print("\n=== sample ===")
    cols = ["ticker", "perp_peak_ret", "perp_ret_24h", "perp_lag_min", "short_funding_24h"]
    with pd.option_context("display.width", 130):
        print(perp[cols].tail(12).to_string(index=False, formatters={
            "perp_peak_ret": "{:+.0%}".format, "perp_ret_24h": "{:+.0%}".format,
            "short_funding_24h": "{:+.2%}".format}))
    print("\n⚠ survivorship-biased; perps that delisted are gone. PLAN.md §4/§6.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
