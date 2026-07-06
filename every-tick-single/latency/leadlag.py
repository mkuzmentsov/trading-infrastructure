#!/usr/bin/env python3
"""Test the user's hypothesis: is RTDS Chainlink a DELAYED version of the real
market? Sample Binance (fast, sub-second trade WS) and RTDS Chainlink at 1s with
precise local timestamps, then cross-correlate their INCREMENTS at lags to find
the lag L that maximizes corr — i.e. does Binance(t) predict Chainlink(t+L)?
Also reports RTDS delivery latency (local_recv - chainlink_source_ts).
If Binance leads by ~L sec, we know Chainlink's close L sec early -> the edge.
Usage: python3 leadlag.py [minutes=8]
"""
import json, time, sys, threading, asyncio
import numpy as np
import websockets

MIN=int(sys.argv[1]) if len(sys.argv)>1 else 8
st={"cl":None,"cl_ts":0,"bin":None,"recv_lat":[]}

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
                        if pts:
                            last=pts[-1]
                            st["cl"]=float(last["value"]); st["cl_ts"]=last.get("timestamp",0)/1000.0
                            st["recv_lat"].append(time.time()-st["cl_ts"])
        except Exception: await asyncio.sleep(2)

async def binance():
    while True:
        try:
            async with websockets.connect("wss://stream.binance.com:9443/ws/btcusdt@trade",ping_interval=20) as ws:
                async for m in ws:
                    try: st["bin"]=float(json.loads(m)["p"])
                    except: pass
        except Exception: await asyncio.sleep(2)

def run(c): asyncio.new_event_loop().run_until_complete(c())
threading.Thread(target=run,args=(rtds,),daemon=True).start()
threading.Thread(target=run,args=(binance,),daemon=True).start()

print(f"collecting {MIN} min at 1s...")
rec=[]
t0=time.time()
while time.time()-t0 < MIN*60:
    if st["cl"] and st["bin"]:
        rec.append((time.time(), st["cl"], st["bin"]))
    time.sleep(1)
print(f"samples: {len(rec)}")
t=np.array([r[0] for r in rec]); cl=np.array([r[1] for r in rec]); bn=np.array([r[2] for r in rec])
# resample to uniform 1s grid
g=np.arange(t[0], t[-1], 1.0)
cli=np.interp(g,t,cl); bni=np.interp(g,t,bn)
dcl=np.diff(cli); dbn=np.diff(bni)
dcl=(dcl-dcl.mean()); dbn=(dbn-dbn.mean())
def xcorr(lag):
    # corr between dbn(t) and dcl(t+lag): positive lag = binance LEADS chainlink
    if lag>0: a,b=dbn[:-lag],dcl[lag:]
    elif lag<0: a,b=dbn[-lag:],dcl[:lag]
    else: a,b=dbn,dcl
    if len(a)<10 or a.std()==0 or b.std()==0: return 0
    return np.corrcoef(a,b)[0,1]
print("\nlead-lag: corr(binance increment @t, chainlink increment @t+L)")
print("  L>0 => Binance LEADS Chainlink by L seconds (the edge)")
best=(-1,0)
for L in range(-5,26):
    c=xcorr(L); 
    if c>best[0]: best=(c,L)
    bar="#"*int(max(c,0)*50)
    print(f"  L={L:+3d}s  corr={c:+.3f} {bar}")
print(f"\nPEAK: corr {best[0]:+.3f} at L={best[1]:+d}s  ->  Binance leads Chainlink by ~{best[1]}s" if best[1]>0 else f"\nPEAK at L={best[1]} (no clean lead)")
rl=np.array(st["recv_lat"][-200:]) if st["recv_lat"] else np.array([0])
print(f"RTDS delivery latency (recv - source_ts): median {np.median(rl):.1f}s")
