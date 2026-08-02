"""Empirical flip frontier for the mintsalvage z-gate (user, 2026-08-02).

Question: at (t_left, lead), what is the MEASURED probability that the side
leading by `lead` bps flips by close? The Gaussian answer is known-wrong here
(MECHANISM.md: predicted 22.5% where reality was 6.58%), so the gate must be
calibrated from tape. Samples: every bar's lead series at a t_left grid;
sigma estimated WITHIN-BAR as std of 1s lead increments over the bar so far
-- the exact estimator the live bot can replicate from its own tick stream.

z = |lead| / (sigma_1s * sqrt(t_left));  frontier = z* with flip rate <= target.
"""
import math, os, pickle, sys
from collections import defaultdict

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
TGRID = [5, 10, 15, 20, 30, 45, 60, 90, 120]
SIG_FLOOR = 0.4          # bps/sqrt(s); dead-tape floor


def load(coin):
    with open(f"{CACHE}/{coin}.pkl", "rb") as fh:
        mk = pickle.load(fh)
    with open(f"{CACHE}/{coin}-leads.pkl", "rb") as fh:
        leads = pickle.load(fh)
    return mk, leads


def samples(coin):
    mk, leads = load(coin)
    out = []
    for ws, m in mk.items():
        ser = leads.get(ws)
        if not ser:
            continue
        # in-bar 1Hz series, tl descending (chronological)
        bar = [(tl, lb) for tl, lb in ser if 0 <= tl <= 300]
        if len(bar) < 60:
            continue
        win = m["win"]
        for tl_target in TGRID:
            past = [lb for tl, lb in bar if tl >= tl_target]
            if len(past) < 30:
                continue
            lead = past[-1]
            if abs(lead) < 0.25:
                continue
            d = [past[i] - past[i - 1] for i in range(1, len(past))]
            mu = sum(d) / len(d)
            sig = math.sqrt(sum((x - mu) ** 2 for x in d) / (len(d) - 1))
            sig = max(sig, SIG_FLOOR)
            z = abs(lead) / (sig * math.sqrt(tl_target))
            flip = (lead > 0) != (win == "UP")
            out.append((coin, ws, tl_target, lead, sig, z, flip))
    return out


def table(rows, label):
    print(f"\n=== {label}: {len(rows)} samples ===")
    zbins = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 99.0]
    agg = defaultdict(lambda: [0, 0])
    for _, _, tl, lead, sig, z, flip in rows:
        for zb in zbins:
            if z <= zb:
                agg[zb][0] += 1
                agg[zb][1] += flip
                break
    print(f"{'z bin':>8s} {'n':>7s} {'flips':>6s} {'flip%':>7s}")
    lo = 0.0
    for zb in zbins:
        n, f = agg[zb]
        if n:
            print(f"{lo:.2f}-{zb:<4.2f} {n:7d} {f:6d} {100*f/n:7.2f}")
        lo = zb
    # cumulative from the top: flip rate for ALL samples with z >= threshold
    print(f"\n{'z >= ':>8s} {'n':>7s} {'flips':>6s} {'flip%':>7s}   (the gate view)")
    for zt in (0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
        sel = [r for r in rows if r[5] >= zt]
        f = sum(r[6] for r in sel)
        if sel:
            print(f"{zt:8.2f} {len(sel):7d} {f:6d} {100*f/len(sel):7.2f}")
    # per-t_left at the chosen-ish gates
    for zt in (1.5, 2.0):
        print(f"\n  per t_left at z>={zt}:")
        for tl in TGRID:
            sel = [r for r in rows if r[2] == tl and r[5] >= zt]
            f = sum(r[6] for r in sel)
            if sel:
                print(f"    tl={tl:3d}s n={len(sel):5d} flips={f:3d} ({100*f/len(sel):5.2f}%)")


if __name__ == "__main__":
    btc = samples("btc")
    table(btc, "btc 5m")
    pooled = []
    for c in ("btc", "eth", "sol", "xrp", "bnb", "doge"):
        try:
            pooled.extend(samples(c))
        except FileNotFoundError:
            pass
    table(pooled, "pooled x6")
