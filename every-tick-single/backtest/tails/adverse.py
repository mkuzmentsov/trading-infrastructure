"""
The decisive test for the maker-on-the-favourite trade.

The view says resting a BUY on the favourite at (1 - tail_ask) carries a
+0.85 to +3.7pp edge *unconditionally*. That number is only real if being
FILLED does not itself predict losing. It usually does: a resting bid gets hit
precisely when the favourite is deteriorating.

Here we rest a bid at a decision time, then replay the tape forward and fill
only when a taker SELL actually prints at or below our price, and compare:

  unconditional win rate   (every bar we would have quoted)
  fill-conditional win rate (only the bars where we actually got hit)

The gap between them IS the adverse selection.

Usage: python3 adverse.py [mrec_root] [decision_tl_seconds]
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]


def run(root: str, decide_tl: float):
    quoted = filled = 0
    q_win = f_win = 0
    fill_px_sum = 0.0
    quoted_px_sum = 0.0
    by_px = defaultdict(lambda: [0, 0, 0, 0])   # quoted, q_win, filled, f_win

    for coin in COINS:
        bars = defaultdict(lambda: {"win": None, "end": 0, "snaps": [], "prints": []})
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
                    if ev == "RES":
                        bars[ws]["win"] = r.get("win")
                    elif ev == "BAR":
                        bars[ws]["end"] = r.get("end") or 0
                    elif ev == "SNAP" and r.get("role") == "cur":
                        tl = r.get("tl")
                        if tl is None or tl <= 0:
                            continue
                        if abs(tl - decide_tl) <= 0.6:
                            bars[ws]["snaps"].append(r)
                        for p in (r.get("trd") or []):
                            bars[ws]["prints"].append(p)

        for ws, b in bars.items():
            if not b["win"] or not b["snaps"]:
                continue
            r = min(b["snaps"], key=lambda x: abs(x["tl"] - decide_tl))
            lead = r.get("lead_bps")
            if lead is None or lead == 0:
                continue
            fav = "UP" if lead > 0 else "DOWN"
            tok = "U" if fav == "UP" else "D"
            tail_ask = r.get("ua") if fav == "DOWN" else r.get("da")
            if tail_ask is None or tail_ask > 0.10 or tail_ask <= 0:
                continue
            px = round(1.0 - tail_ask, 2)          # our resting bid on the favourite
            won = (fav == b["win"])
            end = b["end"] or ws + 300
            t_decide = end - r["tl"]

            quoted += 1
            quoted_px_sum += px
            q_win += 1 if won else 0
            e = by_px[px]
            e[0] += 1
            e[1] += 1 if won else 0

            # forward replay: filled if a taker SELL prints at <= our bid
            hit = False
            for p in b["prints"]:
                ts, ptok, price, size, side = p[0], p[1], p[2], p[3], p[4]
                if ts < t_decide or ts > end:
                    continue
                if ptok != tok or side != "SELL":
                    continue
                if price <= px + 1e-9:
                    hit = True
                    break
            if hit:
                filled += 1
                fill_px_sum += px
                f_win += 1 if won else 0
                e[2] += 1
                e[3] += 1 if won else 0

    print(f"decision at t-{decide_tl:.0f}s before close, favourite = side with the spot lead\n")
    if not quoted:
        print("no quotes")
        return
    qp = quoted_px_sum / quoted
    print(f"  QUOTED (every bar we would rest): {quoted:6d}  avg px {qp:.4f}  "
          f"win {100*q_win/quoted:6.2f}%  edge {100*(q_win/quoted - qp):+6.2f} pp")
    if filled:
        fp = fill_px_sum / filled
        print(f"  FILLED (a taker actually hit us): {filled:6d}  avg px {fp:.4f}  "
              f"win {100*f_win/filled:6.2f}%  edge {100*(f_win/filled - fp):+6.2f} pp")
        print(f"  fill rate {100*filled/quoted:.1f}%   "
              f"ADVERSE SELECTION = {100*(f_win/filled - q_win/quoted):+.2f} pp")
        ev = f_win / filled - fp
        print(f"\n  realised EV per filled share: {ev:+.4f}  "
              f"({'PROFITABLE' if ev > 0 else 'LOSING'})")
    print("\n  by resting price:  px   quoted  q_win%   filled  f_win%   fill%   EV/sh")
    for px in sorted(by_px, reverse=True):
        q, qw, f, fw = by_px[px]
        if q < 40:
            continue
        print(f"    {px:.2f} {q:8d} {100*qw/q:7.2f}% {f:8d} "
              f"{(100*fw/f if f else float('nan')):7.2f}% {100*f/q:6.1f}% "
              f"{((fw/f - px) if f else float('nan')):+8.4f}")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "every-tick-single/data/mrec"
    tl = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    run(root, tl)
