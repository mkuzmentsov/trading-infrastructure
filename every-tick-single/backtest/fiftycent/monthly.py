#!/usr/bin/env python3
"""Monthly cur+2 win rate for a coin — stability/decay check (every-bar bet)."""
import sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
DATA = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
d = pd.read_csv(DATA)
for c in ["open","high","low","close","volume","takerBuyBase"]: d[c]=d[c].astype(float)
d["y"]=(d["close"]>=d["open"]).astype(int); d["clc"]=d["close"].pct_change()
d["range"]=(d["high"]-d["low"])/d["open"]; d["tbr"]=(d["takerBuyBase"]/d["volume"].replace(0,np.nan))-0.5
d["dt"]=pd.to_datetime(d["openTime"],unit="ms"); d["day"]=d["dt"].dt.floor("D"); d["hour"]=d["dt"].dt.hour; d["mon"]=d["dt"].dt.to_period("M").astype(str)
F={}
for k in [1,2,3,6,12,24]: F[f"clc{k}"]=d["clc"].shift(k); F[f"y{k}"]=d["y"].shift(k)-0.5
F["mom3"]=d["clc"].rolling(3).sum().shift(1);F["mom6"]=d["clc"].rolling(6).sum().shift(1);F["mom12"]=d["clc"].rolling(12).sum().shift(1)
v=d["clc"].rolling(12).std().shift(1);F["vol12"]=v;F["zmom6"]=d["clc"].rolling(6).sum().shift(1)/(v*np.sqrt(6));F["revert"]=-d["clc"].shift(1)/v
F["rng6"]=d["range"].rolling(6).mean().shift(1);F["tbr1"]=d["tbr"].shift(1);F["tbr3"]=d["tbr"].rolling(3).mean().shift(1)
F["volz"]=((d["volume"]-d["volume"].rolling(48).mean())/d["volume"].rolling(48).std()).shift(1)
F["hsin"]=np.sin(2*np.pi*d["hour"]/24);F["hcos"]=np.cos(2*np.pi*d["hour"]/24)
X=pd.DataFrame(F,index=d.index);feat=list(X.columns)
dd=pd.concat([X,d["y"].shift(-2).rename("y"),d["day"],d["mon"]],axis=1).dropna().reset_index(drop=True)
days=sorted(dd["day"].unique()); rec={}
for i in range(12,len(days)):
    tr=dd[dd["day"]<days[i]];te=dd[dd["day"]==days[i]]
    if len(te)<50: continue
    gb=HistGradientBoostingClassifier(max_depth=3,learning_rate=0.03,max_iter=200,l2_regularization=2.0,min_samples_leaf=100,random_state=0).fit(tr[feat],tr["y"])
    p=gb.predict_proba(te[feat])[:,1]; m=te["mon"].iloc[0]
    rec.setdefault(m,[0,0]); rec[m][0]+=int(((p>=0.5).astype(int)==te["y"].values).sum()); rec[m][1]+=len(te)
print(f"### {DATA} monthly cur+2")
for m in sorted(rec): w,n=rec[m]; print(f"  {m}  {100*w/n:.2f}%")
