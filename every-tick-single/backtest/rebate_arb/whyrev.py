"""Why did they reverse? Two hypotheses, both testable.

H1 SESSION: flips cluster near session opens (NYSE 13:30, London 08:00,
   Tokyo 00:00 UTC) where volatility jumps. Test: flip rate by UTC hour at
   the 8bps gate, over the whole calibration set.

H2 STALE SIGMA: the z-gate estimates sigma from the bar SO FAR. If vol
   spikes in the final seconds, that estimate is stale, z is overstated, and
   the bot sells a bar it should skip. Test: for each bar, compare realised
   1s vol in the last 40s vs the first 260s.
"""
import math, pickle, time
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
GATE, T = 8.0, 35


def load(c):
    return (pickle.load(open(f"cache/{c}.pkl", "rb")),
            pickle.load(open(f"cache/{c}-leads.pkl", "rb")))


hour = defaultdict(lambda: [0, 0])
vol_rows = []
for c in COINS:
    try:
        mk, leads = load(c)
    except FileNotFoundError:
        continue
    for ws, m in mk.items():
        win = m.get("win"); ser = leads.get(ws)
        if win not in ("UP", "DOWN") or not ser:
            continue
        bar = sorted([(tl, lb) for tl, lb in ser if 0 <= tl <= 300], key=lambda x: -x[0])
        if len(bar) < 120:
            continue
        past = [lb for tl, lb in bar if tl >= T]
        if len(past) < 60:
            continue
        lead = past[-1]
        if abs(lead) < GATE:
            continue
        flip = (lead > 0) != (win == "UP")
        h = time.gmtime(ws).tm_hour
        hour[h][0] += 1; hour[h][1] += flip
        # H2: vol of 1s lead increments, early (tl>=40) vs late (tl<40)
        early = [lb for tl, lb in bar if tl >= 40]
        late = [lb for tl, lb in bar if tl < 40]
        def sd(x):
            d = [x[i] - x[i-1] for i in range(1, len(x))]
            if len(d) < 8: return None
            mu = sum(d)/len(d)
            return math.sqrt(sum((v-mu)**2 for v in d)/(len(d)-1))
        se, sl = sd(early), sd(late)
        if se and sl and se > 0:
            vol_rows.append((sl/se, flip))

print(f"=== H1: flip rate by UTC hour (|lead|>={GATE:.0f}bps at t-{T}s) ===")
print(f"{'hourUTC':>7s} {'n':>5s} {'flips':>5s} {'flip%':>6s}  {'':<22s}")
MARK = {13: "<- NYSE open (SOL)", 23: "<- UTC close (BNB)", 2: "<- Asia am (XRP)",
        8: "<- London open", 0: "<- Tokyo open", 16: "<- funding/US pm"}
tot_n = tot_f = 0
for h in range(24):
    n, f = hour[h]
    tot_n += n; tot_f += f
    if n >= 25:
        print(f"{h:7d} {n:5d} {f:5d} {100*f/n:6.2f}  {MARK.get(h,''):<22s}")
print(f"\npooled: {tot_f}/{tot_n} = {100*tot_f/tot_n if tot_n else 0:.2f}%")

print(f"\n=== H2: late-bar vol vs early-bar vol (ratio), n={len(vol_rows)} ===")
for lo, hi, lab in ((0, 0.8, "late CALMER  <0.8x"), (0.8, 1.25, "steady 0.8-1.25x"),
                    (1.25, 2.0, "late HOTTER 1.25-2x"), (2.0, 99, "late SPIKE   >2x")):
    s = [r for r in vol_rows if lo <= r[0] < hi]
    if len(s) >= 25:
        f = sum(r[1] for r in s)
        print(f"  {lab:22s} n={len(s):5d}  flips={f:3d}  {100*f/len(s):5.2f}%")
