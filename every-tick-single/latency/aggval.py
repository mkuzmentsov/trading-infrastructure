#!/usr/bin/env python3
"""Validate the aggregate as an unlagged Chainlink predictor. Run Aggregator +
RTDS Chainlink; event study on sharp moves in OUR AGGREGATE (vs Binance-alone)
-> Chainlink echo rate + delay. If aggregate echo rate >> Binance's 30%, it's a
clean predictor of Chainlink's 12s-late print.
Usage: python3 aggval.py [minutes=15] [thresh=6]
"""
import asyncio, json, time, sys, threading
import numpy as np
import websockets
sys.path.insert(0, __file__.rsplit("/",1)[0])
from aggregator import Aggregator

MIN=int(sys.argv[1]) if len(sys.argv)>1 else 15
THR=float(sys.argv[2]) if len(sys.argv)>2 else 6.0
st={"cl":None,"bin":None}
async def rtds():
    sub=json.dumps({"action":"subscribe","subscriptions":[{"topic":"crypto_prices_chainlink","type":"*","filters":json.dumps({"symbol":"btc/usd"})}]})
    while True:
        try:
            async with websockets.connect("wss://ws-live-data.polymarket.com",ping_interval=20) as ws:
                await ws.send(sub)
                async for m in ws:
                    d=json.loads(m)
                    for it in (d if isinstance(d,list) else [d]):
                        pts=(it.get("payload") or {}).get("data") if isinstance(it,dict) else None
                        if pts: st["cl"]=float(pts[-1]["value"])
        except Exception: await asyncio.sleep(2)

async def main():
    agg=Aggregator(); agg.start()
    asyncio.ensure_future(rtds())
    print(f"collecting {MIN} min...")
    rec=[]; t0=time.time()
    while time.time()-t0 < MIN*60:
        p=agg.price()
        if p and st["cl"]: rec.append((time.time(), st["cl"], p, agg.px.get("binance")))
        await asyncio.sleep(0.5)
    print(f"samples: {len(rec)}")
    t=np.array([r[0] for r in rec]);cl=np.array([r[1] for r in rec]);ag=np.array([r[2] for r in rec])
    bn=np.array([r[3] if r[3] else np.nan for r in rec])
    g=np.arange(t[0],t[-1],0.5)
    cli=np.interp(g,t,cl);agi=np.interp(g,t,ag)
    bnv=np.interp(g,t,np.nan_to_num(bn,nan=np.nanmean(bn)))
    def event_study(src,name):
        n=len(g);win=8;delays=[];ev=0;echo=0
        i=win
        while i<n-60:
            move=src[i]-src[i-win]
            if abs(move)>=THR:
                ev+=1;target=cli[i-win]+0.5*move
                for j in range(i-win,min(i-win+60,n)):
                    if (move>0 and cli[j]>=target) or (move<0 and cli[j]<=target):
                        delays.append(g[j]-g[i-win]);echo+=1;break
                i+=win
            else: i+=1
        d=np.array(delays) if delays else np.array([0])
        print(f"  {name:16} {ev:4} moves | echo {echo}/{ev} ({echo/max(ev,1)*100:.0f}%) | delay median {np.median(d):.1f}s p25 {np.percentile(d,25):.0f} p75 {np.percentile(d,75):.0f}")
    print(f"\nEVENT STUDY (sharp move >=${THR}/4s -> chainlink echo). Higher echo% = cleaner Chainlink predictor:")
    event_study(bnv,"binance-alone")
    event_study(agi,"OUR-AGGREGATE")
    # xcorr peak of aggregate vs chainlink
    dcl=np.diff(cli);dag=np.diff(agi)
    def xc(L):
        a,b=(dag[:-L],dcl[L:]) if L>0 else (dag,dcl)
        a=a-a.mean();b=b-b.mean()
        return np.corrcoef(a,b)[0,1] if len(a)>20 and a.std()>0 and b.std()>0 else 0
    best=max(((round(L*0.5,1),xc(L)) for L in range(1,50)),key=lambda x:x[1])
    print(f"\n  aggregate xcorr peak: corr {best[1]:+.3f} at L={best[0]:+.1f}s (aggregate leads chainlink)")

if __name__=="__main__": asyncio.run(main())
