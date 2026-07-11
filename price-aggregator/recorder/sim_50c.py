#!/usr/bin/env python3
"""If we rest a 50c limit BUY on an outcome at bar start and hold to resolution,
how many win? Outcome is agg-based (validated 100% vs real PM resolution).

Fill model: a resting BUY at 0.50 fills iff that token's best ask dips to <= 0.50
at some point in the bar (a seller crosses our resting bid). Then we hold to the
bar's resolution. Payout 1.00 if the filled side wins, 0.00 if it loses; cost 0.50.

Usage: python3 recorder/sim_50c.py [data/delay.jsonl] [limit=0.50]
"""
import json, sys
from collections import defaultdict

PATH  = sys.argv[1] if len(sys.argv) > 1 else "data/delay.jsonl"
LIMIT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.50

bars = defaultdict(list)
for line in open(PATH):
    try: r = json.loads(line)
    except Exception: continue
    if r.get("ev") == "s" and r.get("agg"):
        bars[r["ws"]].append(r)

def summarize(name, fills, wins):
    if not fills:
        print(f"  {name:22} no fills"); return
    wr = wins / fills
    ev = wr * 1.0 - LIMIT            # payout 1 if win, cost = LIMIT
    print(f"  {name:22} fills={fills:5d}  win={wins:5d} ({100*wr:4.1f}%)  EV/fill={ev:+.3f}")

n_bars = 0
up_fills = up_wins = dn_fills = dn_wins = 0
both = single = neither = 0
single_wins = 0
for ws, rs in sorted(bars.items()):
    if len(rs) < 5:
        continue
    n_bars += 1
    outcome_up = rs[-1]["agg"] >= rs[0]["agg"]
    up_asks = [r["up_ask"] for r in rs if r.get("up_ask")]
    dn_asks = [r["dn_ask"] for r in rs if r.get("dn_ask")]
    up_fill = bool(up_asks) and min(up_asks) <= LIMIT
    dn_fill = bool(dn_asks) and min(dn_asks) <= LIMIT
    if up_fill:
        up_fills += 1; up_wins += outcome_up
    if dn_fill:
        dn_fills += 1; dn_wins += (not outcome_up)
    if up_fill and dn_fill:
        both += 1
    elif up_fill or dn_fill:
        single += 1
        won = outcome_up if up_fill else (not outcome_up)
        single_wins += won
    else:
        neither += 1

print(f"bars analyzed: {n_bars}   (resting BUY @ {LIMIT:.2f}, hold to resolution)\n")
print("Rest on ONE fixed side:")
summarize("UP only", up_fills, up_wins)
summarize("DOWN only", dn_fills, dn_wins)
summarize("either side (pooled)", up_fills + dn_fills, up_wins + dn_wins)

print("\nRest on BOTH sides at 0.50 (two-sided maker):")
print(f"  both fill (locked 0.50+0.50=1.00, breakeven+2x rebate): {both:5d} ({100*both/n_bars:.0f}%)")
print(f"  only one side fills (a real directional bet):           {single:5d} ({100*single/n_bars:.0f}%)")
if single:
    print(f"      -> single-fill win rate: {single_wins}/{single} = {100*single_wins/single:.1f}%  "
          f"EV/fill={single_wins/single - LIMIT:+.3f}")
print(f"  neither fills (price ran away, no 0.50 touch):          {neither:5d} ({100*neither/n_bars:.0f}%)")
