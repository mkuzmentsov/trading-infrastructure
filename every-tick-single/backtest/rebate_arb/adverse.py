"""THE decisive test: is the model-vs-live gap adverse selection?

The backtest measures flip rate over ALL bars passing the gate (0.54%).
Live we only book a trade on the subset where a COUNTERPARTY EXISTED -- a
resting bid on the corpse. MECHANISM.md's core claim is that fill rate and
adverse selection are the same variable, which predicts the fillable subset
flips MORE often than the unfillable one.

If true, every backtest number in this program is measured on the wrong
population and overstates the edge.
"""
import pickle
from collections import defaultdict
COINS=["btc","eth","sol","xrp","bnb","doge"]; GATE=8.0; TG=[45,35,30,20]
res=defaultdict(lambda: defaultdict(lambda: [0,0]))
for c in COINS:
    try:
        mk=pickle.load(open(f"cache/{c}.pkl","rb")); leads=pickle.load(open(f"cache/{c}-leads.pkl","rb"))
    except FileNotFoundError: continue
    for ws,m in mk.items():
        win=m.get("win"); ser=leads.get(ws); snaps=m.get("snaps")
        if win not in ("UP","DOWN") or not ser or not snaps: continue
        bar=sorted([(tl,lb) for tl,lb in ser if 0<=tl<=300],key=lambda x:-x[0])
        for T in TG:
            past=[lb for tl,lb in bar if tl>=T]
            if len(past)<60: continue
            lead=past[-1]
            if abs(lead)<GATE: continue
            loser="DOWN" if lead>0 else "UP"
            flip=(win==loser)
            best=None
            for s in snaps:
                if 0<=s[0]<=300 and abs(s[0]-T)<=2.0 and (best is None or abs(s[0]-T)<abs(best[0]-T)):
                    best=s
            if best is None: continue
            # bid on the LOSER = our counterparty. s=(tl,ub,ubsz,db,dbsz,ua,uasz,da,dasz)
            bid, bsz = (best[1],best[2]) if loser=="UP" else (best[3],best[4])
            fillable = bid is not None and bid>=0.0099 and (bsz or 0)>0
            k="FILLABLE (a bid exists)" if fillable else "no bid -> no trade"
            res[T][k][0]+=1; res[T][k][1]+=flip
print(f"=== flip rate, gate |lead|>={GATE:.0f}bps, split by whether a counterparty existed ===")
for T in TG:
    print(f"\n  t-{T}s:")
    for k in ("FILLABLE (a bid exists)","no bid -> no trade"):
        n,f=res[T][k]
        if n: print(f"    {k:24s} n={n:5d} flips={f:3d}  {100*f/n:5.2f}%"
                    f"{'   <-- what we ACTUALLY trade' if 'FILL' in k else ''}")
    a=res[T]["FILLABLE (a bid exists)"]; b=res[T]["no bid -> no trade"]
    if a[0] and b[0] and b[1]/b[0]>0:
        print(f"    ratio: fillable flips {(a[1]/a[0])/(b[1]/b[0]):.2f}x more often")
