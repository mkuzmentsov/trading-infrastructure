"""
Two-sided maker pair: rest a BUY on BOTH tokens, collect the spread.

UP + DOWN always pays exactly $1.00 at resolution, so resting both bids at
ub and db costs (ub+db) and pays 1.00. In mrec that sum is < 1.00 on 91.8% of
snapshots, dominant mode 0.99 → +1c per filled pair. No rebate required; the
spread itself is the profit.

The entire question is what happens when only ONE leg fills. This replays the
tape and prices every outcome:

  BOTH filled     profit = 1.00 - (up_px + dn_px)
  ONE filled      three exits, all measured:
                    hold      ride it to resolution (win 1.00 or lose it all)
                    unwind    sell back at the then-best bid
                    complete  cross for the missing leg at its ask
  NEITHER         nothing

Fill model: a taker SELL printing at or below our bid. That assumes we are at
the FRONT of the queue at that price — optimistic, since our order joins behind
whatever size is already resting. Read the fill rates as an upper bound.

Usage: python3 pairarb.py [decision_tl] [offset_ticks]
  offset_ticks: 0 = join the bid, 1 = bid one tick worse (safer, fewer fills)
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
ROOT = "every-tick-single/data/mrec"


def run(decide_tl: float, offset: int):
    both = one = none = 0
    both_pnl = 0.0
    hold_pnl = unwind_pnl = complete_pnl = 0.0
    one_detail = defaultdict(int)
    pair_costs = []

    for coin in COINS:
        bars = defaultdict(lambda: {"win": None, "end": 0, "snap": None,
                                    "d": 9e9, "prints": [], "books": []})
        for fn in sorted(glob.glob(f"{ROOT}/{coin}/{coin}-mrec-*.jsonl.gz")):
            with gzip.open(fn, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    ws, ev = r.get("ws"), r.get("ev")
                    if ws is None:
                        continue
                    b = bars[ws]
                    if ev == "RES":
                        b["win"] = r.get("win")
                    elif ev == "BAR":
                        b["end"] = r.get("end") or 0
                    elif ev == "SNAP" and r.get("role") == "cur":
                        tl = r.get("tl")
                        if tl is None or tl <= 0:
                            continue
                        d = abs(tl - decide_tl)
                        if d < b["d"]:
                            b["d"], b["snap"] = d, r
                        b["books"].append((tl, r.get("ub"), r.get("ua"),
                                           r.get("db"), r.get("da")))
                        for p in (r.get("trd") or []):
                            b["prints"].append(p)

        for ws, b in bars.items():
            r = b["snap"]
            if not b["win"] or r is None or b["d"] > 1.0:
                continue
            ub, db = r.get("ub"), r.get("db")
            if not ub or not db:
                continue
            up_px = round(ub - 0.01 * offset, 2)
            dn_px = round(db - 0.01 * offset, 2)
            if up_px <= 0 or dn_px <= 0:
                continue
            cost = up_px + dn_px
            pair_costs.append(cost)
            end = b["end"] or ws + 300
            t0 = end - r["tl"]

            hit_u = hit_d = None
            for p in b["prints"]:
                ts, tok, price, size, side = p[0], p[1], p[2], p[3], p[4]
                if ts < t0 or ts > end or side != "SELL":
                    continue
                if tok == "U" and hit_u is None and price <= up_px + 1e-9:
                    hit_u = ts
                elif tok == "D" and hit_d is None and price <= dn_px + 1e-9:
                    hit_d = ts
                if hit_u and hit_d:
                    break

            if hit_u and hit_d:
                both += 1
                both_pnl += 1.0 - cost
            elif hit_u or hit_d:
                one += 1
                side = "UP" if hit_u else "DOWN"
                px = up_px if hit_u else dn_px
                one_detail[side] += 1
                won = (side == b["win"])
                hold_pnl += (1.0 - px) if won else -px
                # exits priced off the LAST book before close
                last = max(b["books"], key=lambda x: -x[0]) if b["books"] else None
                if last:
                    _, lub, lua, ldb, lda = last
                    back = lub if hit_u else ldb          # sell back at the bid
                    other = lda if hit_u else lua         # cross for the pair
                    if back:
                        unwind_pnl += (back - px)
                    else:
                        unwind_pnl += (1.0 - px) if won else -px
                    if other:
                        complete_pnl += 1.0 - (px + other)
                    else:
                        complete_pnl += (1.0 - px) if won else -px
            else:
                none += 1

    tot = both + one + none
    if not tot:
        print("no data")
        return
    avg_cost = sum(pair_costs) / len(pair_costs)
    print(f"decision t-{decide_tl:.0f}s, bid offset {offset} tick(s)  "
          f"— {tot} bars, avg pair cost {avg_cost:.4f}\n")
    print(f"  BOTH legs filled : {both:5d} ({100*both/tot:5.1f}%)  "
          f"PnL {both_pnl:+8.2f}  ({both_pnl/max(both,1):+.4f}/pair)")
    print(f"  ONE leg filled   : {one:5d} ({100*one/tot:5.1f}%)  "
          f"UP {one_detail['UP']} / DOWN {one_detail['DOWN']}")
    print(f"       hold to resolution   {hold_pnl:+8.2f}  ({hold_pnl/max(one,1):+.4f}/single)")
    print(f"       unwind at the bid    {unwind_pnl:+8.2f}  ({unwind_pnl/max(one,1):+.4f}/single)")
    print(f"       cross for the pair   {complete_pnl:+8.2f}  ({complete_pnl/max(one,1):+.4f}/single)")
    print(f"  NEITHER filled   : {none:5d} ({100*none/tot:5.1f}%)")
    print()
    for name, single in (("hold", hold_pnl), ("unwind", unwind_pnl),
                         ("cross", complete_pnl)):
        net = both_pnl + single
        print(f"  TOTAL with '{name}' exit: {net:+8.2f} over {tot} bars "
              f"({net/tot:+.4f}/bar)   {'PROFITABLE' if net > 0 else 'LOSING'}")


if __name__ == "__main__":
    run(float(sys.argv[1]) if len(sys.argv) > 1 else 150.0,
        int(sys.argv[2]) if len(sys.argv) > 2 else 0)
