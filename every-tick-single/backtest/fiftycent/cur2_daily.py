#!/usr/bin/env python3
"""Per-day breakdown of the cur+2 walk-forward: every bar is a bet (predict the
model's side), daily win rate = wins/bars."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

d = pd.read_csv("data.csv")
for c in ["open","high","low","close","volume","takerBuyBase"]:
    d[c] = d[c].astype(float)
d["y"]=(d["close"]>=d["open"]).astype(int); d["clc"]=d["close"].pct_change()
d["range"]=(d["high"]-d["low"])/d["open"]; d["tbr"]=(d["takerBuyBase"]/d["volume"].replace(0,np.nan))-0.5
d["dt"]=pd.to_datetime(d["openTime"],unit="ms"); d["day"]=d["dt"].dt.floor("D"); d["hour"]=d["dt"].dt.hour
F={}
for k in [1,2,3,6,12,24]:
    F[f"clc{k}"]=d["clc"].shift(k); F[f"y{k}"]=d["y"].shift(k)-0.5
F["mom3"]=d["clc"].rolling(3).sum().shift(1); F["mom6"]=d["clc"].rolling(6).sum().shift(1)
F["mom12"]=d["clc"].rolling(12).sum().shift(1); vol12=d["clc"].rolling(12).std().shift(1); F["vol12"]=vol12
F["zmom6"]=d["clc"].rolling(6).sum().shift(1)/(vol12*np.sqrt(6)); F["revert"]=-d["clc"].shift(1)/vol12
F["rng6"]=d["range"].rolling(6).mean().shift(1); F["tbr1"]=d["tbr"].shift(1); F["tbr3"]=d["tbr"].rolling(3).mean().shift(1)
F["volz"]=((d["volume"]-d["volume"].rolling(48).mean())/d["volume"].rolling(48).std()).shift(1)
F["hsin"]=np.sin(2*np.pi*d["hour"]/24); F["hcos"]=np.cos(2*np.pi*d["hour"]/24)
X=pd.DataFrame(F,index=d.index); feat=list(X.columns)

H=2
dd=pd.concat([X, d["y"].shift(-H).rename("y"), d["day"]],axis=1).dropna().reset_index(drop=True)
days=sorted(dd["day"].unique()); WARM=12
rows=[]
for i in range(WARM,len(days)):
    tr=dd[dd["day"]<days[i]]; te=dd[dd["day"]==days[i]]
    if len(te)<50: continue
    gb=HistGradientBoostingClassifier(max_depth=3,learning_rate=0.03,max_iter=200,
        l2_regularization=2.0,min_samples_leaf=100,random_state=0).fit(tr[feat],tr["y"])
    p=gb.predict_proba(te[feat])[:,1]
    w=int(((p>=0.5).astype(int)==te["y"].values).sum()); n=len(te)
    rows.append((str(days[i].date()), n, w, w/n))

print(f"cur+2 daily breakdown — every bar is a bet ({len(rows)} days)\n")
print(f"{'date':>11} {'bets':>5} {'wins':>5} {'win%':>6}  {'':<8}")
cum_w=cum_n=0
for dt,n,w,a in rows:
    cum_w+=w; cum_n+=n
    bar = "#"*int((a-0.40)*100) if a>0.40 else ""
    mark = " >=55" if a>=0.55 else (" <=45" if a<=0.45 else "")
    print(f"{dt:>11} {n:>5} {w:>5} {100*a:>5.1f}% {mark:<5} {bar}")
a=np.array([r[3] for r in rows])
print(f"\npooled: {cum_w}/{cum_n} = {100*cum_w/cum_n:.2f}%   (every-bar bet)")
print(f"days >50%: {(a>0.5).sum()}/{len(a)}   >=55%: {(a>=0.55).sum()}   <=45%: {(a<=0.45).sum()}")
print(f"mean {100*a.mean():.2f}%  median {100*np.median(a):.2f}%  min {100*a.min():.1f}%  max {100*a.max():.1f}%")
