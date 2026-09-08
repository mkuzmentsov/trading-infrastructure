"""FULL 10-level SNAP ladders (cur role, tl<=26) -> parquet.  Cheap subset of snap2pq.py:
only the decision window, but every level, plus level counts and cumulative $/share sums.
Note: the UP and DOWN books are the same book (uad[i] mirrors dbd[i] at 1-p) - verified in
the `mirror` columns emitted here."""
import sys, os, gzip, json, glob
from concurrent.futures import ProcessPoolExecutor
import pandas as pd, numpy as np
ROOT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
OUT=sys.argv[1] if len(sys.argv)>1 else "."
TLMAX=26.0
N=10
def lad(v):
    v=v or []
    out=[]
    for i in range(N):
        out += [v[i][0],v[i][1]] if i<len(v) else [np.nan,np.nan]
    out.append(len(v))
    return out
def do(path):
    coin=os.path.basename(path).split("-")[0]
    rows=[]
    with gzip.open(path,"rt") as f:
        for l in f:
            if '"SNAP"' not in l: continue
            try: d=json.loads(l)
            except Exception: continue
            if d.get("role")!="cur": continue
            tl=d.get("tl")
            if tl is None or tl<0 or tl>TLMAX: continue
            r=[coin,d.get("ws"),tl,d.get("t")]
            r+=lad(d.get("uad"))+lad(d.get("ubd"))+lad(d.get("dad"))+lad(d.get("dbd"))
            rows.append(r)
    cn=["coin","ws","tl","t"]+[f"{s}{i}{k}" for s in("uad","ubd","dad","dbd") for i in range(N) for k in("p","s")]
    cn=["coin","ws","tl","t"]
    for s in ("uad","ubd","dad","dbd"):
        cn+= [f"{s}{i}{k}" for i in range(N) for k in ("p","s")]+[f"{s}n"]
    return pd.DataFrame(rows,columns=cn)
if __name__=="__main__":
    coins=["btc","eth","sol","xrp","bnb","doge","hype"]
    files=[p for c in coins for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrec-*.jsonl.gz"))]
    print(len(files),flush=True)
    A=[]
    with ProcessPoolExecutor(10) as ex:
        for i,df in enumerate(ex.map(do,files,chunksize=1)):
            A.append(df)
            if i%100==0: print(i,len(df),flush=True)
    d=pd.concat(A,ignore_index=True)
    for c in d.columns:
        if c!="coin": d[c]=pd.to_numeric(d[c],errors="coerce")
    for c in d.columns:
        if d[c].dtype=="float64" and c not in ("t","ws"): d[c]=d[c].astype("float32")
    d.to_parquet(f"{OUT}/lad10.parquet",index=False)
    print("done",d.shape)
