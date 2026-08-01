"""
Tail-buy opportunity scan over mrec data.

Question: how often can you BUY the eventual winner at <= 0.05 and redeem at
1.00, and when in the bar does that supply exist?

Splits the answer into two regimes, which are NOT the same trade:

  PRE-CLOSE  (tl > 0): the winner is unknown. Buying a 5c tail is a lottery
             ticket - you are paying 5c for something that pays 1.00 only if
             the bar reverses. EV must be judged over ALL tail buys, winners
             and losers alike.

  POST-CLOSE (tl <= 0): the bar has closed, so the winner is determined by the
             price move even though the market has not resolved. Buying the
             winner at 5c here is (modulo settlement risk) riskless.

Reads the ask side, because a BUY lifts the ask: `ua`/`uas` for UP, `da`/`das`
for DOWN. Also counts actual trade prints at <= cap as evidence someone really
was filled there.

Usage: python3 tails.py [data_dir_root] [cap]
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import sys
import time
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def scan(root: str, coin: str, cap: float):
    """Yield one dict per resolved bar."""
    bars: dict[int, dict] = defaultdict(
        lambda: {"win": None, "end": 0, "pre": [], "post": [], "prints": []})
    for fn in sorted(glob.glob(f"{root}/{coin}/{coin}-mrec-*.jsonl.gz")):
        with gzip.open(fn, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ws, ev = r.get("ws"), r.get("ev")
                if ws is None:
                    continue
                if ev == "BAR":
                    bars[ws]["end"] = r.get("end") or 0
                elif ev == "RES":
                    bars[ws]["win"] = r.get("win")
                elif ev == "SNAP":
                    role, tl = r.get("role"), r.get("tl")
                    if role not in ("cur", "post") or tl is None:
                        continue
                    row = (tl, r.get("ua"), r.get("uas"), r.get("da"), r.get("das"))
                    (bars[ws]["pre"] if tl > 0 else bars[ws]["post"]).append(row)
                    for p in (r.get("trd") or []):
                        if p[2] is not None and p[2] <= cap:
                            bars[ws]["prints"].append((p[0], p[1], p[2], p[3], p[4]))
    for ws, b in bars.items():
        if not b["win"] or not b["end"]:
            continue
        yield ws, b


def best(rows, win_is_up: bool, cap: float):
    """(cheapest ask <= cap on the WINNER, its size, tl at that moment)."""
    px = None
    sz = 0.0
    at = None
    for tl, ua, uas, da, das in rows:
        a, s = (ua, uas) if win_is_up else (da, das)
        if a is None or a > cap or not s:
            continue
        if px is None or a < px:
            px, sz, at = a, s, tl
    return px, sz, at


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "every-tick-single/data/mrec"
    cap = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05

    tot = pre_hit = post_hit = 0
    post_rows, pre_rows = [], []
    per_coin = defaultdict(lambda: [0, 0, 0])

    for coin in COINS:
        if not os.path.isdir(f"{root}/{coin}"):
            continue
        for ws, b in scan(root, coin, cap):
            tot += 1
            per_coin[coin][0] += 1
            up = b["win"] == "UP"
            ppx, psz, pat = best(b["pre"], up, cap)
            qpx, qsz, qat = best(b["post"], up, cap)
            if ppx is not None:
                pre_hit += 1
                per_coin[coin][1] += 1
                pre_rows.append((coin, ws, ppx, psz, pat))
            if qpx is not None:
                post_hit += 1
                per_coin[coin][2] += 1
                post_rows.append((coin, ws, qpx, qsz, qat, b["end"]))

    print(f"cap <= {cap}   resolved bars scanned: {tot}\n")
    print("REGIME               bars with the WINNER offered at <=cap")
    print(f"  pre-close  (tl>0)  {pre_hit:5d}  ({100*pre_hit/max(tot,1):.1f}%)")
    print(f"  post-close (tl<=0) {post_hit:5d}  ({100*post_hit/max(tot,1):.1f}%)")
    print()
    print("per coin: bars / pre-close hits / post-close hits")
    for c, (n, a, p) in sorted(per_coin.items()):
        print(f"  {c:5s} {n:5d} {a:5d} ({100*a/max(n,1):4.1f}%) {p:5d} ({100*p/max(n,1):4.1f}%)")

    if post_rows:
        print("\n=== POST-CLOSE (riskless if the lock is right) ===")
        gross = sum(min(sz, 1e9) * (1.0 - px) for _, _, px, sz, _, _ in post_rows)
        print(f"  bars: {len(post_rows)}   full-size gross if every one were swept: ${gross:,.2f}")
        for c, ws, px, sz, tl, end in sorted(post_rows, key=lambda r: r[2])[:15]:
            print(f"    {c:5s} {time.strftime('%a %d %b %H:%M', time.gmtime(end))} UTC "
                  f"ask={px:.3f} size={sz:>9.1f}sh  at t{tl:+.1f}s  "
                  f"-> 25sh pays ${25*(1-px):.2f}")
    if pre_rows:
        print("\n=== PRE-CLOSE (a lottery: the winner is unknown at buy time) ===")
        print(f"  bars where the eventual winner was offered <=cap during the bar: {len(pre_rows)}")
        for c, ws, px, sz, tl in sorted(pre_rows, key=lambda r: r[2])[:10]:
            print(f"    {c:5s} {time.strftime('%a %d %b %H:%M', time.gmtime(ws+300))} UTC "
                  f"ask={px:.3f} size={sz:>9.1f}sh at t{tl:+.1f}s before close")


if __name__ == "__main__":
    main()
