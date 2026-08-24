"""Can a RECENT-sigma gate see it coming? sigma over the 60s before the sale
vs sigma over the whole bar. If vol is already accelerating at decision time,
skip. Measures both the flip rate removed AND the volume kept -- a filter that
kills all flips by refusing every bar is worthless."""
import math, pickle
from collections import defaultdict
COINS=["btc","eth","sol","xrp","bnb","doge"]; GATE,T=8.0,35
rows=[]
for c in COINS:
    try:
        mk=pickle.load(open(f"cache/{c}.pkl","rb")); leads=pickle.load(open(f"cache/{c}-leads.pkl","rb"))
    except FileNotFoundError: continue
    for ws,m in mk.items():
        win=m.get("win"); ser=leads.get(ws)
        if win not in ("UP","DOWN") or not ser: continue
        bar=sorted([(tl,lb) for tl,lb in ser if 0<=tl<=300],key=lambda x:-x[0])
        past=[lb for tl,lb in bar if tl>=T]
        if len(past)<60 or abs(past[-1])<GATE: continue
        flip=(past[-1]>0)!=(win=="UP")
        def sd(x):
            d=[x[i]-x[i-1] for i in range(1,len(x))]
            if len(d)<8: return None
            mu=sum(d)/len(d); return math.sqrt(sum((v-mu)**2 for v in d)/(len(d)-1))
        recent=[lb for tl,lb in bar if T<=tl<T+60]
        sr,sb=sd(recent),sd(past)
        if sr and sb and sb>0: rows.append((sr/sb,flip))
print(f"\n=== recent(60s)/bar sigma ratio, OBSERVABLE at decision time  n={len(rows)} ===")
for lo,hi,lab in ((0,0.9,"calm  <0.9x"),(0.9,1.2,"normal 0.9-1.2x"),(1.2,1.6,"rising 1.2-1.6x"),(1.6,99,"hot   >1.6x")):
    s=[r for r in rows if lo<=r[0]<hi]
    if len(s)>=25:
        f=sum(r[1] for r in s); print(f"  {lab:16s} n={len(s):5d} flips={f:3d}  {100*f/len(s):5.2f}%")
print("\n  cumulative: SKIP bars above threshold ->")
for th in (1.2,1.4,1.6,2.0):
    keep=[r for r in rows if r[0]<th]; f=sum(r[1] for r in keep)
    print(f"    skip >{th:.1f}x : keep {100*len(keep)/len(rows):4.0f}% of bars, flip {100*f/len(keep):5.2f}% (n={len(keep)})")
