#!/usr/bin/env python3
"""Test: is Chainlink a VOLUME-WEIGHTED index of exchanges? Sample RTDS Chainlink
+ 5 exchanges' price & 24h volume simultaneously (~every 3s), fit non-negative
weights reproducing Chainlink from exchange RETURNS (returns cancel the USDT/USD
premium), and compare fitted weights to volume shares. Also reports tracking
error of candidate aggregators (median / mean / volume-weighted / fitted).
Usage: python3 aggfit.py [minutes=6]
"""
import json, time, sys, threading, urllib.request
import numpy as np
import websockets, asyncio

MIN=int(sys.argv[1]) if len(sys.argv)>1 else 6
cl={"px":None}
def U(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=8).read())

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
                        if pts: cl["px"]=float(pts[-1]["value"])
        except Exception: await asyncio.sleep(2)
def rtds_thread():
    asyncio.new_event_loop().run_until_complete(rtds())
threading.Thread(target=rtds_thread,daemon=True).start()

def tickers():
    out={}
    try: b=U("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT");out["binance"]=(float(b["lastPrice"]),float(b["quoteVolume"]))
    except Exception: pass
    try: c=U("https://api.exchange.coinbase.com/products/BTC-USD/ticker");out["coinbase"]=(float(c["price"]),float(c["volume"])*float(c["price"]))
    except Exception: pass
    try:
        k=U("https://api.kraken.com/0/public/Ticker?pair=XBTUSD")["result"];k=k[list(k)[0]]
        out["kraken"]=(float(k["c"][0]),float(k["v"][1])*float(k["c"][0]))
    except Exception: pass
    try: o=U("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT")["data"][0];out["okx"]=(float(o["last"]),float(o["volCcy24h"]))
    except Exception: pass
    try: bs=U("https://www.bitstamp.net/api/v2/ticker/btcusd/");out["bitstamp"]=(float(bs["last"]),float(bs["volume"])*float(bs["last"]))
    except Exception: pass
    return out

print(f"collecting ~{MIN} min...")
EX=["binance","coinbase","kraken","okx","bitstamp"]
samples=[]  # (chainlink, {ex:(px,vol)})
t0=time.time()
while time.time()-t0 < MIN*60:
    if cl["px"]:
        tk=tickers()
        if len([e for e in EX if e in tk])>=4:
            samples.append((cl["px"],tk))
    time.sleep(3)
print(f"samples: {len(samples)}")
# build return series
clp=np.array([s[0] for s in samples])
px={e:np.array([s[1].get(e,(np.nan,np.nan))[0] for s in samples]) for e in EX}
vol={e:np.nanmean([s[1].get(e,(np.nan,np.nan))[1] for s in samples]) for e in EX}
def rets(a): return np.diff(a)/a[:-1]
clr=rets(clp)
R=np.column_stack([rets(px[e]) for e in EX])
good=np.all(np.isfinite(R),axis=1)&np.isfinite(clr)
R=R[good];clr=clr[good]
from scipy.optimize import nnls
w,_=nnls(R,clr);w=w/w.sum() if w.sum()>0 else w
volshare=np.array([vol[e] for e in EX]);volshare=volshare/np.nansum(volshare)
print("\nexchange      fitted-weight   volume-share")
for i,e in enumerate(EX): print(f"  {e:10} {w[i]:>10.3f}     {volshare[i]:>10.3f}")
corr=np.corrcoef(w,volshare)[0,1]
print(f"\ncorr(fitted weights, volume shares) = {corr:+.3f}  (high = Chainlink IS volume-weighted)")
# tracking error of candidate aggregators (price levels, last sample)
def track(agg):
    err=[]
    for c,tk in samples:
        ps=[tk[e][0] for e in EX if e in tk]; vs=[tk[e][1] for e in EX if e in tk]
        if agg=="median": p=np.median(ps)
        elif agg=="mean": p=np.mean(ps)
        elif agg=="volwt": p=np.average(ps,weights=vs)
        elif agg=="fitwt": 
            ee=[e for e in EX if e in tk]; ww=np.array([w[EX.index(e)] for e in ee]); 
            p=np.average([tk[e][0] for e in ee],weights=ww) if ww.sum()>0 else np.mean(ps)
        err.append(abs(p-c))
    return np.mean(err)
print("\nmean |aggregator - chainlink| ($):")
for a in ["median","mean","volwt","fitwt"]:
    print(f"  {a:8} {track(a):.2f}")
