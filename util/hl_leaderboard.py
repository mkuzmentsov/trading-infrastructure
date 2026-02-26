#!/usr/bin/env python3
"""
Hyperliquid leaderboard scanner.

Finds traders who are profitable across day, week, AND month windows,
sorted by a combined score. No credentials required — leaderboard is public.

Usage:
    python3 util/hl_leaderboard.py
    python3 util/hl_leaderboard.py --top 20 --min-account 100000
    python3 util/hl_leaderboard.py --sort month_roi --min-roi-day 0 --min-roi-week 0 --min-roi-month 0.05
    python3 util/hl_leaderboard.py --min-roe-week 0.05 --min-roe-month 0.1
"""

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass
from typing import Optional


LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HL_API_URL = "https://api.hyperliquid.xyz/info"


@dataclass
class TraderStats:
    address: str
    display_name: str
    account_value: float
    day_pnl: float
    day_roi: float
    day_vlm: float
    week_pnl: float
    week_roi: float
    week_vlm: float
    month_pnl: float
    month_roi: float
    month_vlm: float
    alltime_pnl: float
    alltime_roi: float

    @property
    def combined_score(self) -> float:
        """Weighted score: month counts most, then week, then day."""
        return self.month_roi * 0.5 + self.week_roi * 0.3 + self.day_roi * 0.2

    def label(self) -> str:
        return self.display_name if self.display_name else self.address[:10] + "..."


import time as _time


@dataclass
class PerpState:
    account_value: float
    day_roe: float    # day_pnl / account_value
    week_roe: float
    month_roe: float
    position_roes: list[dict]  # per-position returnOnEquity from live positions


def fetch_perp_state(address: str, trader_stats) -> Optional[PerpState]:
    """Fetch clearinghouseState and compute perp ROE metrics."""
    payload = json.dumps({"type": "clearinghouseState", "user": address}).encode()
    req = urllib.request.Request(HL_API_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        account_value = float(data.get("marginSummary", {}).get("accountValue", 0) or 0)
        if account_value <= 0:
            return None
        position_roes = []
        for pos in data.get("assetPositions", []):
            p = pos.get("position", {})
            roe_raw = p.get("returnOnEquity")
            if roe_raw is not None:
                position_roes.append({"coin": p.get("coin", "?"), "roe": float(roe_raw)})
        return PerpState(
            account_value=account_value,
            day_roe=trader_stats.day_pnl / account_value,
            week_roe=trader_stats.week_pnl / account_value,
            month_roe=trader_stats.month_pnl / account_value,
            position_roes=position_roes,
        )
    except Exception:
        return None


def fetch_24h_opens(address: str) -> list[dict]:
    """Fetch positions opened in the last 24 hours for a wallet address."""
    start_ms = int((_time.time() - 86400) * 1000)
    payload = json.dumps({"type": "userFillsByTime", "user": address, "startTime": start_ms}).encode()
    req = urllib.request.Request(HL_API_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            fills = json.loads(r.read())

        # Collect the first open fill per coin (earliest open in the window)
        opens: dict[str, dict] = {}
        for f in fills:
            direction = f.get("dir", "")
            if not direction.startswith("Open"):
                continue
            coin = f["coin"]
            side = "LONG" if "Long" in direction else "SHORT"
            ts_ms = f["time"]
            if coin not in opens or ts_ms < opens[coin]["time_ms"]:
                opens[coin] = {
                    "coin": coin,
                    "side": side,
                    "price": float(f["px"]),
                    "time_ms": ts_ms,
                    "time_str": _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(ts_ms / 1000)),
                }

        return list(opens.values())
    except Exception:
        return []


def fetch_leaderboard() -> list[dict]:
    req = urllib.request.Request(LEADERBOARD_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data.get("leaderboardRows", [])


def parse_row(row: dict) -> Optional[TraderStats]:
    try:
        perf = {window: metrics for window, metrics in row["windowPerformances"]}

        def get(window, key):
            return float(perf.get(window, {}).get(key, 0) or 0)

        return TraderStats(
            address=row["ethAddress"],
            display_name=row.get("displayName", ""),
            account_value=float(row.get("accountValue", 0) or 0),
            day_pnl=get("day", "pnl"),
            day_roi=get("day", "roi"),
            day_vlm=get("day", "vlm"),
            week_pnl=get("week", "pnl"),
            week_roi=get("week", "roi"),
            week_vlm=get("week", "vlm"),
            month_pnl=get("month", "pnl"),
            month_roi=get("month", "roi"),
            month_vlm=get("month", "vlm"),
            alltime_pnl=get("allTime", "pnl"),
            alltime_roi=get("allTime", "roi"),
        )
    except Exception:
        return None


def fmt_pct(v: float) -> str:
    return f"{v * 100:+.2f}%"


def fmt_usd(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:+.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:+.1f}K"
    return f"${v:+.0f}"


def fmt_acc(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def main():
    parser = argparse.ArgumentParser(description="Hyperliquid profitable trader finder")
    parser.add_argument("--top", type=int, default=15, help="Number of results to show (default: 15)")
    parser.add_argument("--min-account", type=float, default=10_000, help="Min account value in USD (default: 10000)")
    parser.add_argument("--min-roi-day", type=float, default=0.0, help="Min ROI for day window, e.g. 0.01 = 1%% (default: 0)")
    parser.add_argument("--min-roi-week", type=float, default=0.0, help="Min ROI for week window (default: 0)")
    parser.add_argument("--min-roi-month", type=float, default=0.0, help="Min ROI for month window (default: 0)")
    parser.add_argument("--max-roi-month", type=float, default=None, help="Max ROI for month window — filters out accounts that started near-zero (e.g. 10.0 = 1000%%)")
    parser.add_argument("--min-vlm-day", type=float, default=0.0, help="Min trading volume in day window in USD (default: 0)")
    parser.add_argument("--min-vlm-week", type=float, default=0.0, help="Min trading volume in week window in USD (default: 0)")
    parser.add_argument("--min-vlm-month", type=float, default=0.0, help="Min trading volume in month window in USD (default: 0)")
    parser.add_argument("--sort", choices=["score", "day_roi", "week_roi", "month_roi", "alltime_pnl", "account"],
                        default="score", help="Sort key (default: score = weighted day/week/month ROI)")
    parser.add_argument("--min-roe-day", type=float, default=None, help="Min perp ROE for day window (e.g. 0.01 = 1%%)")
    parser.add_argument("--min-roe-week", type=float, default=None, help="Min perp ROE for week window")
    parser.add_argument("--min-roe-month", type=float, default=None, help="Min perp ROE for month window")
    parser.add_argument("--check-positions", action=argparse.BooleanOptionalAction, default=True,
                        help="Fetch positions opened in last 24h for each result (default: on, use --no-check-positions to skip)")
    args = parser.parse_args()

    print("Fetching leaderboard...", flush=True)
    rows = fetch_leaderboard()
    print(f"Total entries: {len(rows)}")

    traders = [t for row in rows if (t := parse_row(row)) is not None]

    # Filter: profitable in all three windows + account size + volume activity
    filtered = [
        t for t in traders
        if t.day_roi >= args.min_roi_day
        and t.week_roi >= args.min_roi_week
        and t.month_roi >= args.min_roi_month
        and (args.max_roi_month is None or t.month_roi <= args.max_roi_month)
        and t.account_value >= args.min_account
        and t.day_vlm >= args.min_vlm_day
        and t.week_vlm >= args.min_vlm_week
        and t.month_vlm >= args.min_vlm_month
    ]

    sort_key = {
        "score":      lambda t: t.combined_score,
        "day_roi":    lambda t: t.day_roi,
        "week_roi":   lambda t: t.week_roi,
        "month_roi":  lambda t: t.month_roi,
        "alltime_pnl": lambda t: t.alltime_pnl,
        "account":    lambda t: t.account_value,
    }[args.sort]

    filtered.sort(key=sort_key, reverse=True)

    print(f"Profitable in all windows (day≥{fmt_pct(args.min_roi_day)}, "
          f"week≥{fmt_pct(args.min_roi_week)}, month≥{fmt_pct(args.min_roi_month)}), "
          f"account≥{fmt_acc(args.min_account)}: {len(filtered)} traders")

    # When check_positions is on, scan through the full sorted list and only keep
    # wallets that opened positions in the last 24h, until we have args.top results.
    if args.check_positions:
        print(f"Scanning for wallets with positions opened in last 24h (need {args.top})...\n")
        active_results: list[tuple] = []  # (trader, opens, perp_state)
        scanned = 0
        for t in filtered:
            if len(active_results) >= args.top:
                break
            scanned += 1
            perp = fetch_perp_state(t.address, t)
            _time.sleep(0.2)
            if perp is None:
                print(f"  skip  {t.address}  ({t.label()})  — zero perp account value (spot-only or no margin)", flush=True)
                continue
            if args.min_roe_day is not None and perp.day_roe < args.min_roe_day:
                print(f"  skip  {t.address}  ({t.label()})  — day ROE {fmt_pct(perp.day_roe)} < {fmt_pct(args.min_roe_day)}", flush=True)
                continue
            if args.min_roe_week is not None and perp.week_roe < args.min_roe_week:
                print(f"  skip  {t.address}  ({t.label()})  — week ROE {fmt_pct(perp.week_roe)} < {fmt_pct(args.min_roe_week)}", flush=True)
                continue
            if args.min_roe_month is not None and perp.month_roe < args.min_roe_month:
                print(f"  skip  {t.address}  ({t.label()})  — month ROE {fmt_pct(perp.month_roe)} < {fmt_pct(args.min_roe_month)}", flush=True)
                continue
            opens = fetch_24h_opens(t.address)
            _time.sleep(0.2)
            if not opens:
                print(f"  skip  {t.address}  ({t.label()})  — no positions in last 24h", flush=True)
                continue
            if t.week_roi <= 0 or t.month_roi <= 0:
                print(f"  skip  {t.address}  ({t.label()})  — week or month ROI ≤ 0", flush=True)
                continue
            print(f"  found {t.address}  ({t.label()})  [{len(opens)} position(s)]  "
                  f"ROE day={fmt_pct(perp.day_roe)} week={fmt_pct(perp.week_roe)} month={fmt_pct(perp.month_roe)}", flush=True)
            active_results.append((t, opens, perp))

        top_with_opens = active_results
        print(f"\nScanned {scanned} wallets, found {len(top_with_opens)} active traders.\n")
    else:
        top_with_opens = [(t, [], None) for t in filtered[: args.top]]

    top = [t for t, _, _ in top_with_opens]
    top_perp = [p for _, _, p in top_with_opens]

    print(f"Showing top {len(top)}, sorted by: {args.sort}\n")

    has_perp = any(p is not None for p in top_perp)
    if has_perp:
        header = f"{'#':>3}  {'Address':<44}  {'Name':<16}  {'Acct(perp)':>10}  " \
                 f"{'Day ROE':>9}  {'Day PnL':>10}  " \
                 f"{'Week ROE':>9}  {'Week PnL':>10}  " \
                 f"{'Month ROE':>9}  {'Month PnL':>10}  " \
                 f"{'AllTime PnL':>12}"
    else:
        header = f"{'#':>3}  {'Address':<44}  {'Name':<16}  {'Account':>10}  " \
                 f"{'Day ROI':>9}  {'Day PnL':>10}  " \
                 f"{'Week ROI':>9}  {'Week PnL':>10}  " \
                 f"{'Month ROI':>9}  {'Month PnL':>10}  " \
                 f"{'AllTime PnL':>12}"
    print(header)
    print("-" * len(header))

    for i, (t, perp) in enumerate(zip(top, top_perp), 1):
        if perp is not None:
            print(
                f"{i:>3}  {t.address:<44}  {t.label():<16}  {fmt_acc(perp.account_value):>10}  "
                f"{fmt_pct(perp.day_roe):>9}  {fmt_usd(t.day_pnl):>10}  "
                f"{fmt_pct(perp.week_roe):>9}  {fmt_usd(t.week_pnl):>10}  "
                f"{fmt_pct(perp.month_roe):>9}  {fmt_usd(t.month_pnl):>10}  "
                f"{fmt_usd(t.alltime_pnl):>12}"
            )
        else:
            print(
                f"{i:>3}  {t.address:<44}  {t.label():<16}  {fmt_acc(t.account_value):>10}  "
                f"{fmt_pct(t.day_roi):>9}  {fmt_usd(t.day_pnl):>10}  "
                f"{fmt_pct(t.week_roi):>9}  {fmt_usd(t.week_pnl):>10}  "
                f"{fmt_pct(t.month_roi):>9}  {fmt_usd(t.month_pnl):>10}  "
                f"{fmt_usd(t.alltime_pnl):>12}"
            )

    # Positions opened in last 24h (already fetched above when check_positions is on)
    if args.check_positions and top_with_opens:
        print("\n" + "=" * 80)
        print("POSITIONS OPENED IN LAST 24H")
        print("=" * 80)
        for i, (t, opens, perp) in enumerate(top_with_opens, 1):
            name = t.display_name if t.display_name else t.address[:12] + "..."
            roe_str = ""
            if perp and perp.position_roes:
                roe_parts = "  ".join(f"{r['coin']} ROE={fmt_pct(r['roe'])}" for r in perp.position_roes)
                roe_str = f"\n       Live position ROE: {roe_parts}"
            print(f"\n#{i:>2}  {name} ({t.address}){roe_str}")
            for p in sorted(opens, key=lambda x: x["time_ms"]):
                print(f"       {p['side']:5}  {p['coin']:<8}  @ ${p['price']:,.2f}  opened: {p['time_str']} UTC")

    # Machine-readable wallet list
    print("\n--- Wallet addresses (copy-paste ready) ---")
    for t in top:
        print(t.address)



if __name__ == "__main__":
    main()
