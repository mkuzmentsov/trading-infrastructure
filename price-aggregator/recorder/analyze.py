#!/usr/bin/env python3
"""Measure the AGG -> Chainlink lag from data/delay.jsonl, at sub-second
resolution, and gauge whether the up/down book stays stale long enough to lever.

Usage: python3 recorder/analyze.py [data/delay.jsonl]
"""
import json, sys, statistics
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "data/delay.jsonl"

rows = []
for line in open(PATH):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("ev") == "s" and r.get("agg") and r.get("cl"):
        rows.append(r)

if len(rows) < 50:
    print(f"only {len(rows)} usable rows — let the recorder run longer.")
    sys.exit(0)

t0 = rows[0]["t"]
span_min = (rows[-1]["t"] - t0) / 60
print(f"rows={len(rows)}  span={span_min:.1f} min  cadence~{(rows[-1]['t']-t0)/len(rows):.3f}s")

# ---- resample agg & cl onto a fixed grid (use the sampled values directly) ----
agg = [(r["t"], r["agg"]) for r in rows]
cl  = [(r["t"], r["cl"])  for r in rows]

def corr(xs, ys):
    n = len(xs)
    if n < 20:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a-mx)*(b-my) for a, b in zip(xs, ys))
    sx = (sum((a-mx)**2 for a in xs))**0.5
    sy = (sum((b-my)**2 for b in ys))**0.5
    return cov/(sx*sy) if sx*sy else 0.0

# Build index by rounded time for lag lookups
GRID = 0.25  # sampler cadence
by_t = {round(r["t"]/GRID): r for r in rows}

def val_at(base_t, lag_s, key):
    r = by_t.get(round((base_t + lag_s)/GRID))
    return r[key] if r else None

# ---- cross-correlate agg RETURNS vs cl RETURNS at various lags ----
# corr high at lag L>0 => cl at t+L tracks agg change at t  => AGG leads by L.
print("\nLag scan: corr( d_agg[t-1..t], d_cl[t-1+L..t+L] )  — peak L = lead time")
best = (-2, None)
step = 5  # compare over ~1.25s windows (5 * 0.25s)
for L in [round(x*0.25, 2) for x in range(0, 61, 2)]:  # 0..15s
    xs, ys = [], []
    for i in range(step, len(rows)):
        a1, a0 = rows[i]["agg"], rows[i-step]["agg"]
        c1 = val_at(rows[i]["t"], L, "cl")
        c0 = val_at(rows[i-step]["t"], L, "cl")
        if None in (c1, c0):
            continue
        xs.append(a1-a0); ys.append(c1-c0)
    r = corr(xs, ys)
    if r is not None:
        mark = ""
        if r > best[0]:
            best = (r, L);
        print(f"  L={L:5.2f}s  n={len(xs):5d}  corr={r:+.3f}")
print(f"\n==> AGG leads Chainlink by ~{best[1]}s  (peak corr={best[0]:+.3f})")

# ---- instantaneous lead magnitude ----
diffs = [r["agg"] - r["cl"] for r in rows]
print(f"\nInstantaneous agg-cl:  mean={statistics.mean(diffs):+.1f}  "
      f"median={statistics.median(diffs):+.1f}  std={statistics.pstdev(diffs):.1f}")

# ---- leverage probe: agg says side ITM, is that side's ask still cheap? ----
# For each row with >=45s left: dir = sign(agg - open). If UP, the up-token
# "should" be worth >0.5 and rising; count rows where up_ask <= 0.55 despite
# agg being >$5 above open (stale-cheap window we could lift).
lev = defaultdict(int)
for r in rows:
    if r["secs_left"] < 45 or r["open"] is None:
        continue
    move = r["agg"] - r["open"]
    if abs(move) < 5:
        continue
    lev["signal_rows"] += 1
    if move > 0 and r.get("up_ask") and r["up_ask"] <= 0.55:
        lev["up_stale_cheap"] += 1
    if move < 0 and r.get("dn_ask") and r["dn_ask"] <= 0.55:
        lev["dn_stale_cheap"] += 1
if lev["signal_rows"]:
    stale = lev["up_stale_cheap"] + lev["dn_stale_cheap"]
    print(f"\nLeverage probe (>|$5| agg move, >=45s left):  signal_rows={lev['signal_rows']}  "
          f"stale-cheap(ask<=0.55 on ITM side)={stale}  "
          f"({100*stale/lev['signal_rows']:.0f}%)")
else:
    print("\nLeverage probe: no qualifying signal rows yet.")
