import sys, os, gzip, json, glob
from concurrent.futures import ProcessPoolExecutor
import pandas as pd, numpy as np
ROOT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
OUT="/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq"
COLS=["t","ws","tl","spot","lead_bps","cl","cl_ts","tw","ub","ubs","ua","uas","db","dbs","da","das","evage","vol","volsh"]
def lad(v,n=3):
    v=v or []
    out=[]
    for i in range(n):
        out += [v[i][0],v[i][1]] if i<len(v) else [np.nan,np.nan]
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
            r=[d.get(c) for c in COLS]
            r+=lad(d.get("uad"))+lad(d.get("ubd"))+lad(d.get("dad"))+lad(d.get("dbd"))
            r.append(d.get("trd"))
            rows.append(r)
    cn=COLS+[f"{s}{i}{k}" for s in("uad","ubd","dad","dbd") for i in range(3) for k in("p","s")]+["trd"]
    df=pd.DataFrame(rows,columns=cn); df.insert(0,"coin",coin)
    for c in df.columns:
        if c not in("coin","trd"): df[c]=pd.to_numeric(df[c],errors="coerce").astype("float64")
    return df
if __name__=="__main__":
    coins=["btc","eth","sol","xrp","bnb","doge","hype"]
    files=[p for c in coins for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrec-*.jsonl.gz"))]
    print(len(files),flush=True)
    A=[]
    with ProcessPoolExecutor(12) as ex:
        for i,df in enumerate(ex.map(do,files,chunksize=1)):
            A.append(df)
            if i%100==0: print(i,len(df),flush=True)
    d=pd.concat(A,ignore_index=True)
    for c in d.columns:
        if d[c].dtype=="float64" and c not in("t","ws","cl_ts"): d[c]=d[c].astype("float32")
    d["trd"]=d["trd"].astype(str)
    d.to_parquet(f"{OUT}/snapcur.parquet",index=False)
    print("done",d.shape)
