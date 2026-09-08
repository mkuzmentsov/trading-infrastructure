"""Extract every tick_size_change event + the book/price_change/trade events within
[-3s,+15s] of it for the SAME token, from the raw mrecev streams."""
import gzip,json,glob,os,sys
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
ROOT="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec"
COINS=["btc","eth","sol","xrp","bnb","doge","hype"]
def do(path):
    coin=os.path.basename(path).split("-")[0]
    ev=[]; tsc=[]
    with gzip.open(path,"rt") as f:
        for l in f:
            try: d=json.loads(l)
            except: continue
            et=d.get("et")
            if et=="tick_size_change":
                m=d["m"]; tsc.append((coin,d.get("ws"),d.get("tok"),d["t"],int(m["timestamp"])/1000,m["old_tick_size"],m["new_tick_size"]))
            elif et=="book":
                m=d["m"]; b=m.get("bids") or []; a=m.get("asks") or []
                ev.append((coin,d.get("ws"),d.get("tok"),d["t"],"book",json.dumps(b[-3:] if b else []),json.dumps(a[:3] if a else [])))
            elif et=="price_change":
                ev.append((coin,None,None,d["t"],"pc",json.dumps(d["m"]["ch"]),""))
            elif et=="last_trade_price":
                m=d["m"]; ev.append((coin,d.get("ws"),d.get("tok"),d["t"],"trade",json.dumps([m["price"],m["size"],m["side"]]),""))
    if not tsc: return pd.DataFrame(),pd.DataFrame()
    E=pd.DataFrame(ev,columns=["coin","ws","tok","t","kind","a","b"])
    T=pd.DataFrame(tsc,columns=["coin","ws","tok","t","mts","old","new"])
    keep=[]
    for _,r in T.iterrows():
        w=E[(E.t>=r.t-3)&(E.t<=r.t+15)].copy(); w["tsc_t"]=r.t; w["tsc_ws"]=r.ws; w["tsc_tok"]=r.tok; keep.append(w)
    return T,pd.concat(keep) if keep else pd.DataFrame()
if __name__=="__main__":
    files=[p for c in COINS for p in sorted(glob.glob(f"{ROOT}/{c}/{c}-mrecev-*.jsonl.gz"))]
    print(len(files),"files",flush=True)
    T=[];W=[]
    with ProcessPoolExecutor(8) as ex:
        for i,(t,w) in enumerate(ex.map(do,files,chunksize=2)):
            if len(t): T.append(t); W.append(w)
            if i%50==0: print(i,flush=True)
    T=pd.concat(T); W=pd.concat(W)
    T.to_parquet("tsc.parquet",index=False); W.to_parquet("tsc_win.parquet",index=False)
    print("tsc events",len(T),"window rows",len(W))
