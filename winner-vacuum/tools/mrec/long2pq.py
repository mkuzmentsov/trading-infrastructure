import os,gzip,json,glob,sys
from concurrent.futures import ProcessPoolExecutor
import pandas as pd,numpy as np
ROOT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
COLS=["t","ws","tl","spot","cl","cl_ts","ub","ubs","ua","uas","db","dbs","da","das","evage","vol","volsh"]
def do(path):
    base=os.path.basename(path); coin=base.split("-")[0]
    dur=base.split("-")[1].replace("mrec","").replace("ev","")
    S=[];R=[];B=[];T=[]
    with gzip.open(path,"rt") as f:
        for l in f:
            try: d=json.loads(l)
            except Exception: continue
            e=d.get("ev")
            if e=="SNAP":
                if d.get("role")!="cur": continue
                S.append([coin,dur]+[d.get(c) for c in COLS])
            elif e=="RES": R.append((coin,dur,d["ws"],d["win"]))
            elif e=="BAR": B.append((coin,dur,d["ws"],d.get("end")))
            elif e=="WSE" and d.get("et")=="last_trade_price":
                m=d["m"]; T.append((coin,dur,d.get("ws"),d.get("tok"),float(m["price"]),float(m["size"]),
                                    m.get("side"),int(m["timestamp"])/1000.0))
    return (pd.DataFrame(S,columns=["coin","dur"]+COLS),
            pd.DataFrame(R,columns=["coin","dur","ws","win"]),
            pd.DataFrame(B,columns=["coin","dur","ws","end"]),
            pd.DataFrame(T,columns=["coin","dur","ws","tok","px","sz","side","mts"]))
if __name__=="__main__":
    dirs=["btc-mrec15m","eth-mrec15m","btc-mrec1h","btc-mrec4h","eth-mrec4h","sol-mrec4h","xrp-mrec4h","hype-mrec4h","btc-mrec1d"]
    files=[p for d in dirs for p in sorted(glob.glob(f"{ROOT}/{d}/*.jsonl.gz"))]
    print(len(files),flush=True)
    A=[[],[],[],[]]
    with ProcessPoolExecutor(12) as ex:
        for i,r in enumerate(ex.map(do,files,chunksize=1)):
            for j in range(4): A[j].append(r[j])
            if i%200==0: print(i,flush=True)
    names=["snapL","resL","barL","tradesL"]
    for j,n in enumerate(names):
        d=pd.concat(A[j],ignore_index=True)
        for c in d.columns:
            if c not in("coin","dur","win","tok","side"):
                d[c]=pd.to_numeric(d[c],errors="coerce")
        d.to_parquet(f"pq/{n}.parquet",index=False); print(n,d.shape,flush=True)
