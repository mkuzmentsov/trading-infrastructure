#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/basis.py
The DELTA-HEDGED carry: long HL spot (@107 HYPE/USDC) / short HL perp (HYPE),
same venue, same collateral. Prices the structure against the real fee stack and
measures the basis risk that the funding has to pay for."""
import numpy as np, pandas as pd
H="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
TAKER=4.50   # bps/side, our measured tier, no discounts
p=pd.read_parquet(f"{H}/candles/HYPE-1d.parquet")[["t","c"]].rename(columns={"c":"perp"})
s=pd.read_parquet(f"{H}/candles/at107-1d.parquet")[["t","c"]].rename(columns={"c":"spot"})
d=p.merge(s,on="t").sort_values("t"); d["dt"]=pd.to_datetime(d.t,unit="ms",utc=True)
d["basis_bps"]=(d.perp/d.spot-1)*1e4
f=pd.read_parquet(f"{H}/funding/HYPE.parquet"); f["d"]=pd.to_datetime(f.time,unit="ms",utc=True).dt.strftime("%Y-%m-%d")
fd=f.groupby("d").fundingRate.sum()*1e4        # bps collected per day by a short
d["day"]=d.dt.dt.strftime("%Y-%m-%d"); d=d.merge(fd.rename("fund_bps"),left_on="day",right_index=True,how="left")
print(f"overlap {len(d)} days  {d.dt.min():%Y-%m-%d} -> {d.dt.max():%Y-%m-%d}")
print(f"\nBASIS (perp vs spot, each venue-leg against the OTHER LEG of the same pair -- this is a")
print(f"true basis, not a cross-venue level comparison):")
print(f"  mean {d.basis_bps.mean():+.2f} bps  median {d.basis_bps.median():+.2f}  sd {d.basis_bps.std():.2f}")
print(f"  p5 {d.basis_bps.quantile(.05):+.2f}  p95 {d.basis_bps.quantile(.95):+.2f}  min {d.basis_bps.min():+.1f} max {d.basis_bps.max():+.1f}")
print(f"  P(perp > spot) = {(d.basis_bps>0).mean()*100:.1f}%   (positive basis <=> longs pay funding)")
print(f"  daily change in basis: sd {d.basis_bps.diff().std():.2f} bps  <- the risk the carry must cover")

print(f"\nCARRY ECONOMICS, delta-hedged, per unit notional PER LEG:")
ent=2*TAKER; ex=2*TAKER; rt=ent+ex
print(f"  entry = spot taker {TAKER} + perp taker {TAKER} = {ent:.1f} bps;  exit likewise -> round trip {rt:.1f} bps")
for label,apr in [("full sample",d.fund_bps.mean()*365/1e4*100),
                  ("last 180 d", d.tail(180).fund_bps.mean()*365/1e4*100),
                  ("last  90 d", d.tail(90).fund_bps.mean()*365/1e4*100)]:
    per_day=apr/365*100   # bps/day
    print(f"  {label}: funding {apr:+6.2f} %/yr = {per_day:5.2f} bps/day -> break-even hold {rt/per_day:5.1f} days"
          f"; 30-day hold nets {30*per_day-rt:+6.1f} bps; 90-day {90*per_day-rt:+6.1f} bps")
print(f"\n  ⚠️ maker entry on both legs would cost {2*1.5*2:.1f} bps round trip instead of {rt:.1f},")
print(f"     halving break-even -- but a resting order's fill is adversely selected and this")
print(f"     program has measured that cost before. Not modelled here; needs a queue sim.")

print(f"\nROBUSTNESS of the hedged carry (net bps per 30-day hold, by month of entry):")
d["m"]=d.dt.dt.strftime("%Y-%m")
g=d.groupby("m").fund_bps.mean()*30-rt
print("  " + "  ".join(f"{m}:{v:+.0f}" for m,v in g.items()))
print(f"  months where a 30-day hedged hold LOSES money: {(g<0).sum()} / {len(g)}")
print(f"  worst month {g.idxmin()} {g.min():+.0f} bps ; best {g.idxmax()} {g.max():+.0f} bps")
neg=d[d.fund_bps<0]
print(f"\n  days of NEGATIVE funding (short pays): {len(neg)}/{len(d)} = {len(neg)/len(d)*100:.1f}%,"
      f" mean {neg.fund_bps.mean():.2f} bps on those days")

# ============================================================================
# CORRECTION: the month table above uses FUNDING ONLY and therefore OVERSTATES
# the trade. A hedged position also carries basis mark-to-market:
#   long spot S0 / short perp P0, exit S1/P1
#   PnL = (S1-S0) - (P1-P0) = -(basis1 - basis0)
# So the honest net for an H-day hold is:
#   funding_collected  -  (basis_exit - basis_entry)  -  18 bps
# ============================================================================
print("\n" + "="*78)
print("HONEST VERSION — funding AND basis mark-to-market, overlapping H-day holds")
print("="*78)
d=d.reset_index(drop=True)
cf=np.concatenate([[0],np.nancumsum(d.fund_bps.values)])
b=d.basis_bps.values
for Hd in (7,30,90):
    n=len(d)-Hd
    fund=cf[Hd:Hd+n]-cf[:n]
    dbasis=b[Hd:Hd+n]-b[:n]
    net=fund-dbasis-rt
    # overlapping -> effective independent n, and a day-clustered SE via non-overlapping blocks
    nonov=net[::Hd]
    se=nonov.std(ddof=1)/np.sqrt(len(nonov))
    ann=net.mean()*365/Hd/1e4*100
    print(f"\n  hold {Hd:3d}d   n_overlap={n}  n_indep={len(nonov)}")
    print(f"    funding      {fund.mean():+8.1f} bps   basis drag {-dbasis.mean():+8.1f} bps   fees {-rt:+6.1f}")
    print(f"    NET          {net.mean():+8.1f} bps  ({ann:+.1f} %/yr)   sd {net.std():.1f}   "
          f"SE(indep) {se:.1f}   t={net.mean()/se:+.2f}")
    print(f"    P(profitable hold) {(net>0).mean()*100:.1f}%   worst {net.min():+.0f}  best {net.max():+.0f}")
    print(f"    Sharpe per hold {net.mean()/net.std():.2f}  -> annualised {net.mean()/net.std()*np.sqrt(365/Hd):.2f}")
    # leave-one-month-out on the 30d version
    if Hd==30:
        mm=d.m.values[:n]; loo=[]
        for m in sorted(set(mm)):
            loo.append((m, net[mm!=m].mean()))
        loo=sorted(loo,key=lambda x:x[1])
        print(f"    LOO worst: drop {loo[0][0]} -> {loo[0][1]:+.1f} bps ; all {len(loo)} LOO positive? {all(v>0 for _,v in loo)}")
        pos=[(m,net[mm==m].mean()) for m in sorted(set(mm))]
        print(f"    months with NEGATIVE mean 30d net: {sum(1 for _,v in pos if v<0)}/{len(pos)}"
              f"  worst {min(pos,key=lambda x:x[1])}")
print("""
READ: the basis is a real risk, not a rounding error -- daily basis change sd (11.4 bps)
is ~4x the daily carry (2.6 bps). Funding-only accounting flatters this trade.""")
