"""Build a 'mixed' venue dataset = the 16 crypto alts + uncorrelated MACRO proxies on one
daily calendar, so the multi-asset TSM can be tested on a genuinely diversified universe
(roadmap option D — the real lever on the Deflated Sharpe).

Macro daily closes come from the Yahoo Finance chart API (JSON, no key). Each macro series
is reindexed onto the crypto daily (365-day) calendar and forward-filled over weekends/
holidays, so the calendar — and ppy=365 — matches the existing crypto baseline exactly
(apples-to-apples). Everything is written into the store under venue='mixed'.

Usage:  PYTHONPATH=src python3 scripts/build_mixed_universe.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Bar, Symbol, VenueId
from algo_trading_bot.data.store import PointInTimeStore

CRYPTO = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
          "LINK", "DOT", "LTC", "TRX", "ATOM", "BCH", "ETC", "XLM"]

# Uncorrelated-to-crypto asset classes: US + intl equities, long + mid bonds, gold,
# broad commodities + oil, US dollar. (Ticker -> store symbol.)
MACRO = {
    "SPY": "SPY", "QQQ": "QQQ", "TLT": "TLT", "IEF": "IEF",
    "GLD": "GLD", "DBC": "DBC", "USO": "USO", "UUP": "UUP",
}


def fetch_yahoo_daily(ticker: str, start: datetime, end: datetime) -> pd.Series:
    """Daily close series from Yahoo's chart API. Index = tz-aware UTC midnight dates."""
    p1, p2 = int(start.timestamp()), int(end.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    idx = pd.to_datetime([datetime.fromtimestamp(t, tz=timezone.utc).date() for t in ts], utc=True)
    s = pd.Series(close, index=idx, name=ticker).astype(float)
    return s[~s.index.duplicated(keep="last")].dropna()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crypto-source", choices=["binance", "yahoo"], default="binance",
                    help="binance (store, BTC 2017 / alts 2021) or yahoo (X-USD, BTC 2014, point-in-time)")
    ap.add_argument("--venue", default="mixed", help="store venue to write (e.g. mixed, mixed_long)")
    ap.add_argument("--start-year", type=int, default=2017)
    args = ap.parse_args()

    store = PointInTimeStore("./data")
    start = datetime(args.start_year, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)

    # 1) crypto closes. Sample on a BUSINESS-DAY calendar (weekdays) so macro has no forced
    #    weekend zero-returns (those understate macro vol -> over-size it). Crypto's weekend move
    #    lands in the Friday->Monday return. ppy stays 1d/365 (uniform; DSR/PBO are per-bar).
    if args.crypto_source == "binance":
        crypto = store.close_panel([Symbol(s) for s in CRYPTO], start, end, "1d", venue="binance")
        crypto.index = pd.to_datetime(crypto.index, utc=True).normalize()
    else:  # yahoo: X-USD per name, point-in-time (each from its listing)
        cols = {}
        for sym in CRYPTO:
            try:
                s = fetch_yahoo_daily(f"{sym}-USD", start, end)
                cols[sym] = s
                print(f"  {sym}-USD  {s.index[0].date()} -> {s.index[-1].date()} ({len(s)})")
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}-USD FAILED: {exc}")
        crypto = pd.DataFrame(cols)
        crypto.index = crypto.index.normalize()
    # calendar starts where crypto first exists (both sleeves present from the start)
    cal = pd.bdate_range(crypto.index.min(), crypto.index.max(), tz="UTC")
    crypto = crypto.reindex(cal).ffill()
    print(f"crypto panel ({args.crypto_source}): {crypto.shape[1]} symbols, {len(cal)} business days "
          f"({cal[0].date()} -> {cal[-1].date()})")

    # 2) macro closes from Yahoo, reindexed onto the business-day calendar (ffill holidays only)
    macro_cols = {}
    for ticker, sym in MACRO.items():
        try:
            s = fetch_yahoo_daily(ticker, start, end)
            s.index = s.index.normalize()
            macro_cols[sym] = s.reindex(cal).ffill()
            n = int(macro_cols[sym].notna().sum())
            print(f"  {ticker:4s} -> {sym:4s}  {n} days aligned")
        except Exception as exc:  # noqa: BLE001
            print(f"  {ticker:4s} FAILED: {exc}")
    macro = pd.DataFrame(macro_cols)

    # 3) correlation sanity — verify macro is genuinely less correlated with crypto
    rets = pd.concat([crypto, macro], axis=1).pct_change().dropna(how="all")
    cc = rets[CRYPTO].corr()
    crypto_avg = cc.where(~np.eye(len(CRYPTO), dtype=bool)).stack().mean()
    xcorr = rets[CRYPTO].corrwith(rets[list(MACRO.values())].mean(axis=1)).mean()
    print(f"\navg pairwise corr WITHIN crypto = {crypto_avg:+.2f}")
    print(f"avg corr crypto vs macro-basket  = {xcorr:+.2f}   (lower = more diversification)")

    # 4) write everything into the target venue (o=h=l=c=close; ts==knowable_at, point-in-time)
    full = pd.concat([crypto, macro], axis=1)
    n_written = 0
    for sym in full.columns:
        col = full[sym].dropna()
        bars = [
            Bar(Symbol(sym), ts.to_pydatetime(), float(c), float(c), float(c), float(c),
                0.0, VenueId(args.venue), knowable_at=ts.to_pydatetime())
            for ts, c in col.items()
        ]
        store.append_bars(bars, "1d")
        n_written += len(bars)
    print(f"\nwrote {n_written} bars across {full.shape[1]} symbols under venue='{args.venue}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
