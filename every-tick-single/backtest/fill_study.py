#!/usr/bin/env python3
"""Deep fill-rate + win-rate breakdown for resting bids at various prices, on our
Polymarket paper datasets. Print-exact: a resting BUY at P on a token fills iff a
trade prints <= P on that token during the bar. Win = outcome == held side.

Sections: (1) price grid pooled, (2) by coin, (3) by day/regime, (4) fill timing,
(5) two-sided view. Rebate uses the calibrated 0.014*p(1-p) $/share (E7).

Usage: python3 fill_study.py [date ...]   (default: all committed date dirs)
"""
import json, math, os, sys, statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import experiments as X

PRICES = [0.40, 0.42, 0.44, 0.46, 0.47, 0.48, 0.49, 0.50, 0.51, 0.52]


def fills_for(b, side, P):
    """Would a resting bid at P on `side` fill? (print on that token <= P).
    Returns (filled, first_fill_secs_left or None)."""
    hits = [pr[0] for pr in b["prints"] if pr[1] == side and 0 < pr[2] <= P]
    return (True, max(hits)) if hits else (False, None)


def rebate(P):
    return 0.014 * P * (1 - P)   # calibrated 20% capture (E7)


def collect(dates, root):
    bars = {}
    for d in dates:
        dd = os.path.join(root, d)
        if os.path.isdir(dd):
            for k, v in X.load(dd).items():
                v["day"] = d
                bars[k] = v
    return [b for b in bars.values() if b["outcome"] in ("UP", "DOWN") and b["prints"]]


def grid(bars, sides=("UP", "DOWN"), label=""):
    print(f"\n{'='*78}\nPRICE GRID {label} — resting bid, print-exact fills, both sides pooled")
    print(f"{'P':>5} {'bars':>6} {'fills':>6} {'fill%':>6} {'wins':>6} {'win%':>6} {'brkevn':>6} {'edge':>7} {'EV/sh':>8} {'EV+reb':>8}")
    for P in PRICES:
        nb = fills = wins = 0
        for b in bars:
            for s in sides:
                nb += 1
                f, _ = fills_for(b, s, P)
                if f:
                    fills += 1
                    wins += (b["outcome"] == s)
        if not fills:
            continue
        q = wins / fills
        ev = q * (1 - P) - (1 - q) * P
        evr = ev + rebate(P)
        print(f"{P:5.2f} {nb:6} {fills:6} {fills/nb*100:5.1f}% {wins:6} {q*100:5.1f}% {P*100:5.0f}% {q-P:+7.3f} {ev:+8.4f} {evr:+8.4f}")


def by_coin(bars):
    print(f"\n{'='*78}\nBY COIN at P=0.46 / 0.48 / 0.50 (fill% , win%)")
    print(f"{'coin':>5}  " + "  ".join(f"{p:>16.2f}" for p in (0.46, 0.48, 0.50)))
    coins = sorted(set(b["coin"] for b in bars))
    for c in coins:
        cb = [b for b in bars if b["coin"] == c]
        cells = []
        for P in (0.46, 0.48, 0.50):
            nb = fills = wins = 0
            for b in cb:
                for s in ("UP", "DOWN"):
                    nb += 1
                    f, _ = fills_for(b, s, P)
                    if f:
                        fills += 1; wins += (b["outcome"] == s)
            cells.append(f"{fills/nb*100:4.0f}%/{(wins/fills*100 if fills else 0):4.0f}%")
        print(f"{c:>5}  " + "  ".join(f"{x:>16}" for x in cells))


def by_day(bars):
    print(f"\n{'='*78}\nBY DAY (regime) at P=0.48 — fill%, win%, EV/sh")
    print(f"{'day':>12} {'bars':>6} {'fill%':>6} {'win%':>6} {'EV/sh':>8}")
    for d in sorted(set(b["day"] for b in bars)):
        db = [b for b in bars if b["day"] == d]
        nb = fills = wins = 0
        for b in db:
            for s in ("UP", "DOWN"):
                nb += 1
                f, _ = fills_for(b, s, 0.48)
                if f:
                    fills += 1; wins += (b["outcome"] == s)
        q = wins / fills if fills else 0
        print(f"{d:>12} {len(db):6} {fills/nb*100:5.1f}% {q*100:5.1f}% {q*0.52-(1-q)*0.48:+8.4f}")


def fill_timing(bars):
    print(f"\n{'='*78}\nFILL TIMING at P=0.48 — when in the bar fills land, and win% by bucket")
    buckets = {"0-30s": [0, 0], "30-60s": [0, 0], "60-120s": [0, 0], "120-240s": [0, 0], "240-300s": [0, 0]}
    for b in bars:
        for s in ("UP", "DOWN"):
            f, sl = fills_for(b, s, 0.48)
            if not f:
                continue
            elapsed = 300 - sl
            k = ("0-30s" if elapsed <= 30 else "30-60s" if elapsed <= 60 else
                 "60-120s" if elapsed <= 120 else "120-240s" if elapsed <= 240 else "240-300s")
            buckets[k][0] += (b["outcome"] == s); buckets[k][1] += 1
    print(f"{'bucket':>10} {'fills':>6} {'win%':>6}")
    for k, (w, n) in buckets.items():
        if n:
            print(f"{k:>10} {n:6} {w/n*100:5.1f}%")


def two_sided(bars):
    print(f"\n{'='*78}\nTWO-SIDED view at P=0.48 — per bar: both/one/neither fill")
    both = one = neither = 0
    pair_pnl = single_pnl = 0.0
    for b in bars:
        fu, _ = fills_for(b, "UP", 0.48)
        fd, _ = fills_for(b, "DOWN", 0.48)
        if fu and fd:
            both += 1; pair_pnl += (1 - 2*0.48)   # locked pair
        elif fu or fd:
            one += 1
            s = "UP" if fu else "DOWN"
            single_pnl += (0.52 if b["outcome"] == s else -0.48)
        else:
            neither += 1
    n = len(bars)
    print(f"  bars={n}  both-fill={both} ({both/n*100:.0f}%)  one-fill={one} ({one/n*100:.0f}%)  neither={neither} ({neither/n*100:.0f}%)")
    print(f"  both-fill locked pnl/bar=+{(1-2*0.48):.2f}  total from pairs={pair_pnl:+.1f}")
    print(f"  single-fill total pnl={single_pnl:+.1f}  avg/single={single_pnl/one if one else 0:+.3f}")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(here, "..", "tests", "data")
    dates = sys.argv[1:] or sorted(d for d in os.listdir(root) if d.startswith("202"))
    bars = collect(dates, root)
    print(f"Fill study — {len(bars)} settled bars w/ prints, days: {', '.join(dates)}")
    grid(bars)
    by_coin(bars)
    by_day(bars)
    fill_timing(bars)
    two_sided(bars)


if __name__ == "__main__":
    main()
