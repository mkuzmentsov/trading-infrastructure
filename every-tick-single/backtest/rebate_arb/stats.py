"""Separate the DETERMINISTIC terms (pair lock + rebate) from the RANDOM one
(unpaired directional PnL) and t-test the latter. Totals alone are misleading:
an unpaired 100-share leg at 0.50 is a +-$50 coin flip, so a 4-day total can
swing hundreds of dollars on noise and look like an edge."""
import math, sys
import fast

def analyse(coins, pu, pd, entry, size=100.0):
    recs = fast.run(coins, pu, pd, size, entry, cancel_at_open=True)
    if not recs: return None
    lock, reb, dirs = 0.0, 0.0, []
    both = 0
    for r in recs:
        reb += r["rebate"]
        if r["both"]:
            both += 1
            paired = min(r["fu"], r["fd"])
            lock += paired * (1.0 - pu - pd)
            # residual unpaired part of a both-fill bar is directional
            resid_u, resid_d = r["fu"] - paired, r["fd"] - paired
            if resid_u or resid_d:
                pay = (resid_u if r["win"]=="UP" else 0) + (resid_d if r["win"]=="DOWN" else 0)
                dirs.append(pay - resid_u*pu - resid_d*pd)
        else:
            pay = (r["fu"] if r["win"]=="UP" else 0) + (r["fd"] if r["win"]=="DOWN" else 0)
            dirs.append(pay - r["fu"]*pu - r["fd"]*pd)
    n = len(recs)
    dsum = sum(dirs)
    dmean = dsum/len(dirs) if dirs else 0.0
    dsd = (math.sqrt(sum((x-dmean)**2 for x in dirs)/(len(dirs)-1)) if len(dirs)>1 else 0.0)
    se = dsd/math.sqrt(len(dirs)) if dirs else 0.0
    t = dmean/se if se else 0.0
    edge = lock + reb                      # deterministic
    return dict(n=n, both=both, lock=lock, reb=reb, dsum=dsum, dsd=dsd,
                t=t, ndir=len(dirs), edge=edge, tot=edge+dsum,
                risk_sd=dsd*math.sqrt(len(dirs)))

if __name__ == "__main__":
    print(f"{'config':32s} {'bars':>5s} {'both%':>6s} {'LOCK$':>9s} {'REBATE$':>9s} "
          f"{'dir$':>10s} {'dir_t':>6s} {'EDGE$':>9s} {'noise_sd$':>10s}")
    print("-"*118)
    for entry in ("next3","next2","next1"):
        for p in (0.52,0.51,0.50,0.49,0.48):
            a = analyse(fast.COINS, p, p, entry)
            if not a: continue
            print(f"{entry+' '+f'{p:.2f}/{p:.2f}':32s} {a['n']:5d} {100*a['both']/a['n']:5.0f}% "
                  f"{a['lock']:+9.2f} {a['reb']:+9.2f} {a['dsum']:+10.2f} {a['t']:+6.2f} "
                  f"{a['edge']:+9.2f} {a['risk_sd']:10.0f}")
