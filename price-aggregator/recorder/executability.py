#!/usr/bin/env python3
"""Executability study: is the ~2.5s agg->Chainlink lead actually TRADEABLE?

Fixes the old leverage probe, which used "agg move from bar-open" — contaminated
by the persistent ~$53 BTCUSDT/USD basis. Here the signal is a ROLLING-BASIS lead
gap that cancels the basis and slow drift, isolating fresh moves Chainlink hasn't
absorbed yet:

    spread    = agg - cl
    basis     = trailing mean(spread) over BASIS_S     # ~$53 + slow drift
    lead_gap  = spread - basis                          # fresh, un-absorbed move

Then, on lead_gap events, it asks the only question that matters: if we lift the
in-the-money side's ask and hold to resolution, do we win, and what's the EV —
versus buying that side with no signal (baseline).

Usage: python3 recorder/executability.py [data/delay.jsonl]
"""
import json, sys, statistics
from collections import defaultdict, deque

PATH   = sys.argv[1] if len(sys.argv) > 1 else "data/delay.jsonl"
BASIS_S   = 60.0     # trailing window for the basis
MIN_LEFT  = 20       # only trade with >= this many secs left in the bar
LOOK_S    = 2.5      # the measured lead horizon
FEE       = 0.0      # per-share taker fee (Polymarket crypto fee ~0; set to test)

rows = []
for line in open(PATH):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("ev") == "s" and r.get("agg") and r.get("cl"):
        rows.append(r)
rows.sort(key=lambda r: r["t"])
if len(rows) < 500:
    print(f"only {len(rows)} rows — let it run longer."); sys.exit(0)

# ---- per-bar outcome from the AGGREGATE open/close ----
# Validated 2026-07-09: sign(agg_close - agg_open) matches real PM resolution
# 100% (98/98); the RTDS cl proxy only 52%. So label outcomes from agg.
bars = defaultdict(list)
for r in rows:
    bars[r["ws"]].append(r)
outcome_up = {}   # ws -> True if bar resolved UP
for ws, rs in bars.items():
    open_agg = rs[0]["agg"]
    close_agg = rs[-1]["agg"]
    outcome_up[ws] = close_agg >= open_agg

# ---- rolling basis -> lead_gap ----
win = deque()
gap_of = {}
for i, r in enumerate(rows):
    spread = r["agg"] - r["cl"]
    win.append((r["t"], spread))
    while win and r["t"] - win[0][0] > BASIS_S:
        win.popleft()
    basis = statistics.mean(s for _, s in win)
    gap_of[i] = spread - basis

gaps = list(gap_of.values())
gstd = statistics.pstdev(gaps)
print(f"rows={len(rows)}  span={(rows[-1]['t']-rows[0]['t'])/60:.0f} min")
print(f"lead_gap: mean={statistics.mean(gaps):+.2f}  std={gstd:.2f}  (basis removed)\n")

# ---- confirm the lead survives basis removal: gap now vs cl move over LOOK_S ----
import bisect
ts = [r["t"] for r in rows]
def cl_at(t):
    j = bisect.bisect_left(ts, t)
    for k in (j, j-1, j+1):
        if 0 <= k < len(rows) and abs(rows[k]["t"] - t) <= 1.0:
            return rows[k]["cl"]
    return None
xs, ys = [], []
for i, r in enumerate(rows):
    clf = cl_at(r["t"] + LOOK_S)
    if clf is not None:
        xs.append(gap_of[i]); ys.append(clf - r["cl"])
mx, my = statistics.mean(xs), statistics.mean(ys)
cov = sum((a-mx)*(b-my) for a, b in zip(xs, ys))
sx = (sum((a-mx)**2 for a in xs))**0.5; sy = (sum((b-my)**2 for b in ys))**0.5
print(f"lead check: corr(lead_gap, Chainlink move over next {LOOK_S}s) = {cov/(sx*sy):+.3f}")
print("  (>0 => a fresh gap predicts Chainlink catching up in that direction)\n")

# ---- DECISIVE: does the up/down BOOK track real-time agg or the lagged RTDS? ----
# up_mid ~ market's implied P(up). If its moves sync with agg at lag 0, the book
# is real-time (no edge). If they sync with cl (i.e. lag ~+2.5s behind agg), the
# book follows the lagged feed and the lead IS tradeable.
def _corr(a, b):
    if len(a) < 20: return 0.0
    ma, mb = statistics.mean(a), statistics.mean(b)
    cv = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    sa = (sum((x-ma)**2 for x in a))**0.5; sb = (sum((y-mb)**2 for y in b))**0.5
    return cv/(sa*sb) if sa*sb else 0.0

STEP = 4  # ~1s return window (4 * 0.25s)
def book_lag_scan(ref_key, label):
    print(f"book vs {label}: corr( d_up_mid[t], d_{label}[t-L] ) — peak L = book lags {label} by L")
    best = (-2, None)
    for L in [round(x*0.25, 2) for x in range(-4, 17, 2)]:   # -1s .. +4s
        xs2, ys2 = [], []
        for i in range(STEP, len(rows)):
            r, rp = rows[i], rows[i-STEP]
            um = r.get("up_bid"); ua = r.get("up_ask")
            pm = rp.get("up_bid"); pa = rp.get("up_ask")
            if None in (um, ua, pm, pa): continue
            refn = cl_at(r["t"] - L) if ref_key == "cl" else None
            refp = cl_at(rp["t"] - L) if ref_key == "cl" else None
            if ref_key == "agg":
                jn = bisect.bisect_left(ts, r["t"] - L); jp = bisect.bisect_left(ts, rp["t"] - L)
                refn = rows[jn]["agg"] if 0 <= jn < len(rows) else None
                refp = rows[jp]["agg"] if 0 <= jp < len(rows) else None
            if None in (refn, refp): continue
            xs2.append((ua+um)/2 - (pa+pm)/2); ys2.append(refn - refp)
        c = _corr(xs2, ys2)
        if c > best[0]: best = (c, L)
        print(f"    L={L:+5.2f}s  corr={c:+.3f}")
    print(f"  => book lags {label} by ~{best[1]}s (peak {best[0]:+.3f})\n")
    return best

b_agg = book_lag_scan("agg", "agg")
b_cl  = book_lag_scan("cl", "cl")

# ---- executability: lift the ITM ask on gap events, hold to resolution ----
def run(thresh):
    n = win_ = 0
    ev_sum = ask_sum = 0.0
    stale_up = 0            # book ask still <= 0.55 on the ITM side (liftable cheap)
    repriced = still = 0    # did the ITM ask move UP over LOOK_S (book lagging us)?
    for i, r in enumerate(rows):
        if r["secs_left"] < MIN_LEFT:
            continue
        g = gap_of[i]
        if abs(g) < thresh:
            continue
        up = g > 0
        ask = r.get("up_ask") if up else r.get("dn_ask")
        if not ask or ask >= 1.0:
            continue
        won = outcome_up[r["ws"]] if up else (not outcome_up[r["ws"]])
        n += 1; win_ += won
        ev_sum += (1.0 if won else 0.0) - ask - FEE
        ask_sum += ask
        if ask <= 0.55:
            stale_up += 1
        # book lag: did the ITM ask rise over the next LOOK_S? (we'd have gotten in cheaper)
        fut = None
        j = bisect.bisect_left(ts, r["t"] + LOOK_S)
        for k in (j, j-1, j+1):
            if 0 <= k < len(rows) and abs(rows[k]["t"] - (r["t"]+LOOK_S)) <= 1.0 and rows[k]["ws"] == r["ws"]:
                fut = rows[k].get("up_ask") if up else rows[k].get("dn_ask"); break
        if fut is not None:
            if fut > ask + 0.005: repriced += 1
            else: still += 1
    if not n:
        return None
    return dict(n=n, win=win_/n, ask=ask_sum/n, ev=ev_sum/n, total=ev_sum,
                cheap=stale_up/n, lag=(repriced/(repriced+still) if repriced+still else 0))

print(f"Event study — lift the ITM ask & hold to resolution (>= {MIN_LEFT}s left):")
print(f"{'thresh$':>8} {'events':>7} {'win%':>6} {'avgAsk':>7} {'EV/sh':>7} {'totalEV':>9} {'ask<=.55':>9} {'bookLag%':>9}")
for th in (round(x, 1) for x in (gstd, gstd*1.5, gstd*2, gstd*3)):
    res = run(th)
    if res:
        print(f"{th:>8.1f} {res['n']:>7} {100*res['win']:>5.0f}% {res['ask']:>7.3f} "
              f"{res['ev']:>+7.3f} {res['total']:>+9.1f} {100*res['cheap']:>8.0f}% {100*res['lag']:>8.0f}%")

# ---- baseline: buy the ITM-by-cl side with NO signal, same filter ----
bn = bwin = 0; bev = 0.0
for i, r in enumerate(rows):
    if r["secs_left"] < MIN_LEFT:
        continue
    up = (r["cl"] >= (bars[r["ws"]][0].get("open") or r["cl"]))  # side currently winning per cl
    ask = r.get("up_ask") if up else r.get("dn_ask")
    if not ask or ask >= 1.0:
        continue
    won = outcome_up[r["ws"]] if up else (not outcome_up[r["ws"]])
    bn += 1; bwin += won; bev += (1.0 if won else 0.0) - ask - FEE
if bn:
    print(f"\nbaseline (no gap signal, buy cl-leading side): events={bn} win={100*bwin/bn:.0f}% "
          f"EV/sh={bev/bn:+.3f}")
print("\nEV/sh > 0 with win% clearly above avgAsk => the lead is tradeable; "
      "bookLag% = share of events where the ITM ask rose over the next 2.5s.")
