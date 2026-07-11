#!/usr/bin/env python3
"""How well can we predict bar cur+H's outcome from info known now?
H=0 = the bar about to open (what we had before). H=2 = a bar starting 10min out
(pre-open, fair 0.50). Walk-forward daily, OOS accuracy + significance per horizon."""
import sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

DATA = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
print(f"### {DATA}")
d = pd.read_csv(DATA)
for c in ["open","high","low","close","volume","takerBuyBase"]:
    d[c] = d[c].astype(float)
d["ret"] = d["close"]/d["open"]-1.0
d["y"] = (d["close"]>=d["open"]).astype(int)
d["clc"] = d["close"].pct_change()
d["range"] = (d["high"]-d["low"])/d["open"]
d["tbr"] = (d["takerBuyBase"]/d["volume"].replace(0,np.nan))-0.5
d["dt"] = pd.to_datetime(d["openTime"],unit="ms"); d["day"]=d["dt"].dt.floor("D"); d["hour"]=d["dt"].dt.hour

F={}
for k in [1,2,3,6,12,24]:
    F[f"clc{k}"]=d["clc"].shift(k); F[f"y{k}"]=d["y"].shift(k)-0.5
F["mom3"]=d["clc"].rolling(3).sum().shift(1); F["mom6"]=d["clc"].rolling(6).sum().shift(1)
F["mom12"]=d["clc"].rolling(12).sum().shift(1)
vol12=d["clc"].rolling(12).std().shift(1); F["vol12"]=vol12
F["zmom6"]=d["clc"].rolling(6).sum().shift(1)/(vol12*np.sqrt(6))
F["revert"]=-d["clc"].shift(1)/vol12
F["rng6"]=d["range"].rolling(6).mean().shift(1)
F["tbr1"]=d["tbr"].shift(1); F["tbr3"]=d["tbr"].rolling(3).mean().shift(1)
F["volz"]=((d["volume"]-d["volume"].rolling(48).mean())/d["volume"].rolling(48).std()).shift(1)
F["hsin"]=np.sin(2*np.pi*d["hour"]/24); F["hcos"]=np.cos(2*np.pi*d["hour"]/24)
X=pd.DataFrame(F,index=d.index); feat=list(X.columns)

print(f"{'horizon':>8} {'OOS days':>9} {'mean acc':>9} {'std':>6} {'z(>0.5)':>8} {'days>=55%':>10}")
for H in (0,1,2,3):
    yH = d["y"].shift(-H)                      # outcome of bar cur+H
    dd = pd.concat([X, yH.rename("y"), d["day"]], axis=1).dropna().reset_index(drop=True)
    days = sorted(dd["day"].unique()); WARM=12
    daily=[]
    for i in range(WARM,len(days)):
        tr=dd[dd["day"]<days[i]]; te=dd[dd["day"]==days[i]]
        if len(te)<50: continue
        gb=HistGradientBoostingClassifier(max_depth=3,learning_rate=0.03,max_iter=200,
            l2_regularization=2.0,min_samples_leaf=100,random_state=0).fit(tr[feat],tr["y"])
        p=gb.predict_proba(te[feat])[:,1]
        daily.append(((p>=0.5).astype(int)==te["y"].values).mean())
    a=np.array(daily); z=(a.mean()-0.5)/(a.std()/np.sqrt(len(a)))
    print(f"cur+{H:<5} {len(a):>9} {a.mean():>9.4f} {a.std():>6.3f} {z:>+8.2f} {(a>=0.55).sum():>7}/{len(a)}")
