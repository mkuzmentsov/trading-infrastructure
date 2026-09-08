import os,gzip,json,glob
from concurrent.futures import ProcessPoolExecutor
import pandas as pd,numpy as np
ROOT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
def do(path):
    coin=os.path.basename(path).split("-")[0]; rows=[]
    with gzip.open(path,"rt") as f:
        for l in f:
            if '"RB"' not in l: continue
            try: d=json.loads(l)
            except Exception: continue
            if d.get("ev")!="RB": continue
            rb=d.get("rb3") or []; ra=d.get("ra3") or []
            rows.append((coin,d["ws"],d["tok"],d["t"],bool(d.get("match")),
                         rb[0][0] if rb else np.nan, rb[0][1] if rb else np.nan,
                         ra[0][0] if ra else np.nan, ra[0][1] if ra else np.nan,
                         sum(x[1] for x in ra) if ra else np.nan))
    return pd.DataFrame(rows,columns=["coin","ws","tok","t","match","rb0","rb0s","ra0","ra0s","rasum"])
if __name__=="__main__":
    files=[p for c in ["btc","eth","sol","xrp","bnb","doge","hype"] for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrec-*.jsonl.gz"))]
    with ProcessPoolExecutor(12) as ex: A=list(ex.map(do,files,chunksize=1))
    d=pd.concat(A,ignore_index=True); d.to_parquet("pq/rb2.parquet",index=False); print(d.shape)
