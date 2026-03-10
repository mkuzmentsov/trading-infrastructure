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
import os
import time as _time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional


LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HL_API_URL = "https://api.hyperliquid.xyz/info"
HL_LAUNCH_MS = 1_698_796_800_000  # Nov 1, 2023 — Hyperliquid mainnet launch

DEFAULT_WALLETS_FILE = os.path.join(os.path.dirname(__file__), "wallets-of-interest.txt")


def load_wallets_of_interest(path: str) -> list[str]:
    try:
        with open(path) as f:
            return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


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


@dataclass
class PerpState:
    account_value: float
    day_roe: float
    week_roe: float
    month_roe: float
    position_roes: list[dict]


@dataclass
class ActivityStats:
    trades_24h: int
    trades_7d: int
    trades_30d: int
    first_trade_ms: Optional[int]          # oldest known fill timestamp
    opens_24h: list[dict] = field(default_factory=list)  # opened positions in last 24h

    @property
    def wallet_age_str(self) -> str:
        if self.first_trade_ms is None:
            return "?"
        days = (_time.time() * 1000 - self.first_trade_ms) / (1000 * 86400)
        if days >= 365:
            return f"{days / 365:.1f}y"
        if days >= 30:
            return f"{days / 30:.0f}mo"
        return f"{int(days)}d"


def _hl_post(payload: dict, timeout: int = 10) -> Optional[list | dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(HL_API_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_perp_state(address: str, trader_stats) -> Optional[PerpState]:
    """Fetch clearinghouseState and compute perp ROE metrics."""
    data = _hl_post({"type": "clearinghouseState", "user": address})
    if not data:
        return None
    account_value = float(data.get("marginSummary", {}).get("accountValue", 0) or 0)
    if account_value <= 0:
        return None
    position_roes = []
    for pos in data.get("assetPositions", []):
        p = pos.get("position", {})
        roe_raw = p.get("returnOnEquity")
        if roe_raw is not None:
            position_roes.append({"coin": p.get("coin", "?"), "roe": float(roe_raw)})
    # Use the leaderboard's ROI directly — it's computed by HL against beginning-of-period
    # equity, which is more accurate than dividing current-period PnL by current account value.
    return PerpState(
        account_value=account_value,
        day_roe=trader_stats.day_roi,
        week_roe=trader_stats.week_roi,
        month_roe=trader_stats.month_roi,
        position_roes=position_roes,
    )


def fetch_activity_stats(address: str) -> ActivityStats:
    """
    Fetch trade counts (24h / 7d / 30d), 24h opens list, and wallet age.
    Makes 2 API calls:
      1. Last 30 days of fills  → trade counts + 24h opens
      2. From HL launch to now  → first fill timestamp (wallet age)
    """
    now_ms = int(_time.time() * 1000)
    start_30d = now_ms - 30 * 86400 * 1000
    start_7d  = now_ms -  7 * 86400 * 1000
    start_24h = now_ms -      86400 * 1000

    # --- 30-day fills ---
    fills_30d = _hl_post({"type": "userFillsByTime", "user": address, "startTime": start_30d}) or []

    trades_24h = sum(1 for f in fills_30d if f.get("time", 0) >= start_24h)
    trades_7d  = sum(1 for f in fills_30d if f.get("time", 0) >= start_7d)
    trades_30d = len(fills_30d)

    # Build 24h opens list (first open per coin in the 24h window)
    opens: dict[str, dict] = {}
    for f in fills_30d:
        if f.get("time", 0) < start_24h:
            continue
        direction = f.get("dir", "")
        if not direction.startswith("Open"):
            continue
        coin = f["coin"]
        side = "LONG" if "Long" in direction else "SHORT"
        ts_ms = f["time"]
        if coin not in opens or ts_ms > opens[coin]["time_ms"]:
            opens[coin] = {
                "coin": coin,
                "side": side,
                "price": float(f["px"]),
                "time_ms": ts_ms,
                "time_str": _time.strftime("%Y-%m-%d %H:%M:%S", _time.gmtime(ts_ms / 1000)),
            }

    # --- Wallet age: earliest fill since HL launch ---
    # Use a shorter timeout; active traders can have tens of thousands of fills and a full
    # history fetch is often slow. Fall back to the oldest fill in the 30d window if it fails.
    first_trade_ms: Optional[int] = None
    _time.sleep(0.2)
    all_fills = _hl_post({"type": "userFillsByTime", "user": address, "startTime": HL_LAUNCH_MS}, timeout=8)
    if all_fills:
        timestamps = [f["time"] for f in all_fills if "time" in f]
        if timestamps:
            first_trade_ms = min(timestamps)
    else:
        # Fallback: use the oldest fill we already have from the 30d window
        ts_30d = [f["time"] for f in fills_30d if "time" in f]
        if ts_30d:
            first_trade_ms = min(ts_30d)

    return ActivityStats(
        trades_24h=trades_24h,
        trades_7d=trades_7d,
        trades_30d=trades_30d,
        first_trade_ms=first_trade_ms,
        opens_24h=list(opens.values()),
    )


def fetch_leaderboard() -> list[dict]:
    req = urllib.request.Request(LEADERBOARD_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("leaderboardRows", [])
    except Exception as e:
        print(f"ERROR: Failed to fetch leaderboard: {e}")
        return []


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
    except Exception as e:
        print(f"WARNING: Failed to parse leaderboard row: {e}  row={str(row)[:120]}")
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
    parser.add_argument("--sort", choices=["score", "day_roi", "week_roi", "month_roi", "alltime_pnl", "alltime_roi", "account"],
                        default="score", help="Sort key (default: score = weighted day/week/month ROI)")
    parser.add_argument("--min-roe-day", type=float, default=None, help="Min perp ROE for day window (e.g. 0.01 = 1%%)")
    parser.add_argument("--min-roe-week", type=float, default=None, help="Min perp ROE for week window")
    parser.add_argument("--min-roe-month", type=float, default=None, help="Min perp ROE for month window")
    parser.add_argument("--check-positions", action=argparse.BooleanOptionalAction, default=True,
                        help="Fetch positions opened in last 24h for each result (default: on, use --no-check-positions to skip)")
    parser.add_argument("--wallets-file", default=DEFAULT_WALLETS_FILE,
                        help=f"File with wallet addresses to always check first (default: {DEFAULT_WALLETS_FILE})")
    args = parser.parse_args()

    print("Fetching leaderboard...", flush=True)
    rows = fetch_leaderboard()
    print(f"Total entries: {len(rows)}")

    traders = [t for row in rows if (t := parse_row(row)) is not None]

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
        and t.alltime_pnl > 0
    ]

    # Prepend wallets-of-interest (always checked first, bypass filters)
    wallets_of_interest = load_wallets_of_interest(args.wallets_file)
    if wallets_of_interest:
        trader_by_addr = {t.address.lower(): t for t in traders}
        pinned = [trader_by_addr[w] for w in wallets_of_interest if w in trader_by_addr]
        pinned_addrs = {t.address.lower() for t in pinned}
        filtered = pinned + [t for t in filtered if t.address.lower() not in pinned_addrs]
        if pinned:
            print(f"Prepended {len(pinned)} wallet(s) of interest: {', '.join(t.address for t in pinned)}")
        missing = [w for w in wallets_of_interest if w not in trader_by_addr]
        if missing:
            print(f"WARNING: {len(missing)} wallet(s) of interest not found in leaderboard: {', '.join(missing)}")

    sort_key = {
        "score":       lambda t: t.combined_score,
        "day_roi":     lambda t: t.day_roi,
        "week_roi":    lambda t: t.week_roi,
        "month_roi":   lambda t: t.month_roi,
        "alltime_pnl": lambda t: t.alltime_pnl,
        "alltime_roi": lambda t: t.alltime_roi,
        "account":     lambda t: t.account_value,
    }[args.sort]

    filtered.sort(key=sort_key, reverse=True)

    vlm_parts = []
    if args.min_vlm_day > 0:
        vlm_parts.append(f"day_vlm≥{fmt_acc(args.min_vlm_day)}")
    if args.min_vlm_week > 0:
        vlm_parts.append(f"week_vlm≥{fmt_acc(args.min_vlm_week)}")
    if args.min_vlm_month > 0:
        vlm_parts.append(f"month_vlm≥{fmt_acc(args.min_vlm_month)}")
    vlm_str = (", " + ", ".join(vlm_parts)) if vlm_parts else ""
    print(f"Profitable in all windows (day≥{fmt_pct(args.min_roi_day)}, "
          f"week≥{fmt_pct(args.min_roi_week)}, month≥{fmt_pct(args.min_roi_month)}, alltime_pnl>0), "
          f"account≥{fmt_acc(args.min_account)}{vlm_str}: {len(filtered)} traders")

    if args.check_positions:
        print(f"Scanning for wallets with positions opened in last 24h (need {args.top})...\n")
        active_results: list[tuple] = []  # (trader, activity, perp)
        scanned = 0
        for t in filtered:
            if len(active_results) >= args.top:
                break
            scanned += 1

            perp = fetch_perp_state(t.address, t)
            _time.sleep(0.2)
            if perp is None:
                print(f"  skip  {t.address}  ({t.label()})  — zero perp account value", flush=True)
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

            activity = fetch_activity_stats(t.address)
            _time.sleep(0.2)
            if not activity.opens_24h:
                print(f"  skip  {t.address}  ({t.label()})  — no positions opened in last 24h", flush=True)
                continue
            if t.week_roi < 0 or t.month_roi < 0:
                print(f"  skip  {t.address}  ({t.label()})  — week or month ROI < 0", flush=True)
                continue

            print(f"  found {t.address}  ({t.label()})  "
                  f"age={activity.wallet_age_str}  "
                  f"trades 24h={activity.trades_24h} 7d={activity.trades_7d} 30d={activity.trades_30d}  "
                  f"ROE day={fmt_pct(perp.day_roe)} week={fmt_pct(perp.week_roe)} month={fmt_pct(perp.month_roe)}",
                  flush=True)
            active_results.append((t, activity, perp))

        top_with_data = active_results
        print(f"\nScanned {scanned} wallets, found {len(top_with_data)} active traders.\n")
    else:
        top_with_data = [(t, None, None) for t in filtered[: args.top]]

    top       = [t for t, _, _  in top_with_data]
    top_act   = [a for _, a, _  in top_with_data]
    top_perp  = [p for _, _, p  in top_with_data]

    print(f"Showing top {len(top)}, sorted by: {args.sort}\n")

    has_perp = any(p is not None for p in top_perp)
    if has_perp:
        header = (f"{'#':>3}  {'Address':<44}  {'Name':<16}  {'Age':>6}  "
                  f"{'T/24h':>5}  {'T/7d':>5}  {'T/30d':>6}  "
                  f"{'Acct(perp)':>10}  "
                  f"{'Day ROE':>9}  {'Day PnL':>10}  "
                  f"{'Wk ROE':>9}  {'Wk PnL':>10}  "
                  f"{'Mo ROE':>9}  {'Mo PnL':>10}  "
                  f"{'AllTime PnL':>12}")
    else:
        header = (f"{'#':>3}  {'Address':<44}  {'Name':<16}  "
                  f"{'Account':>10}  "
                  f"{'Day ROI':>9}  {'Day PnL':>10}  "
                  f"{'Wk ROI':>9}  {'Wk PnL':>10}  "
                  f"{'Mo ROI':>9}  {'Mo PnL':>10}  "
                  f"{'AllTime PnL':>12}")
    print(header)
    print("-" * len(header))

    for i, (t, act, perp) in enumerate(zip(top, top_act, top_perp), 1):
        age  = act.wallet_age_str if act else "?"
        t24  = str(act.trades_24h) if act else "?"
        t7   = str(act.trades_7d)  if act else "?"
        t30  = str(act.trades_30d) if act else "?"
        if perp is not None:
            print(
                f"{i:>3}  {t.address:<44}  {t.label():<16}  {age:>6}  "
                f"{t24:>5}  {t7:>5}  {t30:>6}  "
                f"{fmt_acc(perp.account_value):>10}  "
                f"{fmt_pct(perp.day_roe):>9}  {fmt_usd(t.day_pnl):>10}  "
                f"{fmt_pct(perp.week_roe):>9}  {fmt_usd(t.week_pnl):>10}  "
                f"{fmt_pct(perp.month_roe):>9}  {fmt_usd(t.month_pnl):>10}  "
                f"{fmt_usd(t.alltime_pnl):>12}"
            )
        else:
            print(
                f"{i:>3}  {t.address:<44}  {t.label():<16}  "
                f"{fmt_acc(t.account_value):>10}  "
                f"{fmt_pct(t.day_roi):>9}  {fmt_usd(t.day_pnl):>10}  "
                f"{fmt_pct(t.week_roi):>9}  {fmt_usd(t.week_pnl):>10}  "
                f"{fmt_pct(t.month_roi):>9}  {fmt_usd(t.month_pnl):>10}  "
                f"{fmt_usd(t.alltime_pnl):>12}"
            )

    if args.check_positions and top_with_data:
        print("\n" + "=" * 80)
        print("POSITIONS OPENED IN LAST 24H")
        print("=" * 80)
        for i, (t, act, perp) in enumerate(top_with_data, 1):
            name = t.display_name if t.display_name else t.address[:12] + "..."
            age_str = f"  age={act.wallet_age_str}" if act else ""
            trade_str = (f"  trades: 24h={act.trades_24h} / 7d={act.trades_7d} / 30d={act.trades_30d}"
                         if act else "")
            roe_str = ""
            if perp and perp.position_roes:
                roe_parts = "  ".join(f"{r['coin']} ROE={fmt_pct(r['roe'])}" for r in perp.position_roes)
                roe_str = f"\n       Live position ROE: {roe_parts}"
            print(f"\n#{i:>2}  {name} ({t.address}){age_str}{trade_str}{roe_str}")
            opens = act.opens_24h if act else []
            for p in sorted(opens, key=lambda x: x["time_ms"]):
                print(f"       {p['side']:5}  {p['coin']:<8}  @ ${p['price']:,.2f}  opened: {p['time_str']} UTC")

    print("\n--- Wallet addresses (copy-paste ready) ---")
    for t in top:
        print(t.address)


if __name__ == "__main__":
    main()
