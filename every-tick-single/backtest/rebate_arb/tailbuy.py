"""TAIL-BUY (FAK) study: when a side's ASK touches <=cap (1c/2c/3c) INTRABAR
(tl>0, before close -- post-close 1c asks on the winner are the separate,
already-known settlement-snipe edge and are EXCLUDED), buy FAK and hold to
resolution. Win pays ~(1-p-fee), loss costs (p+fee). Breakeven win rate at
1c after the 0.07*p*(1-p) taker fee: ~1.07%.

Cache: 1Hz book snaps (tl, ub,ubs,db,dbs,ua,uas,da,das) + all prints, ground
truth RES. Ask side indices: UP=(5,6), DOWN=(7,8).
"""
import math, time, collections
import fast

FEE = 0.07

def touches(cap=0.01, tl_hi=300.0, tl_lo=0.0):
    """Yield one record per (market, side) whose ask touches <=cap intrabar:
    (coin, ws, side, first_tl, ask_px, ask_sz, won, bar_range, bar_vol)."""
    for coin in fast.COINS:
        for ws, m in fast.load(coin).items():
            # bar volume from prints in cur window; also UP-bid range as vol proxy
            vol = 0.0
            for tl, t, px, sz, tside in m["sells"]:
                if 0.0 < tl <= tl_hi:
                    vol += sz
            lo = hi = None
            for s in m["snaps"]:
                if s[0] > tl_hi or s[0] <= 150: continue
                b = s[1]
                if b is None: continue
                lo = b if lo is None else min(lo, b)
                hi = b if hi is None else max(hi, b)
            rng = None if lo is None else hi - lo
            for side, ai, asz in (("UP", 5, 6), ("DOWN", 7, 8)):
                first = None
                for s in m["snaps"]:                    # tl descending
                    if s[0] > tl_hi or s[0] <= tl_lo: continue
                    a, az = s[ai], s[asz]
                    if a is not None and a <= cap + 1e-9 and az > 0:
                        first = (s[0], a, az); break
                if first:
                    won = (m["win"] == side)
                    yield dict(coin=coin, ws=ws, side=side, tl=first[0],
                               px=first[1], sz=first[2], won=won,
                               rng=rng, vol=vol)

def ev_per_share(p, won):
    f = FEE * p * (1 - p)
    return (1.0 - p - f) if won else (-p - f)

def agg(rows, keyfn, label):
    b = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in rows:
        k = keyfn(r)
        if k is None: continue
        e = ev_per_share(r["px"], r["won"])
        b[k][0] += 1; b[k][1] += 1 if r["won"] else 0
        b[k][2] += e; b[k][3] += min(r["sz"], 1000)
    print(f"\n  by {label}:")
    print(f"    {'bucket':>16s} {'n':>6s} {'win%':>6s} {'EV c/sh':>8s} {'avail sh(med-ish)':>12s}")
    for k in sorted(b):
        n, w, ev, sz = b[k]
        print(f"    {str(k):>16s} {n:6d} {100*w/n:5.2f}% {100*ev/n:+8.3f} {sz/n:12.0f}")
