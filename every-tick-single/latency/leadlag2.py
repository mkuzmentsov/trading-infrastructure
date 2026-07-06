#!/usr/bin/env python3
"""Cleaner lead-lag: 0.5s sampling, longer window, plus an EVENT STUDY — when
Binance moves sharply (|Δ| over a 4s window > threshold), measure the delay until
Chainlink echoes that move (crosses half the move in the same direction). Robust
to quiet-market noise. Confirms/kills the "Chainlink is delayed ~10s" hypothesis.
Usage: python3 leadlag2.py [minutes=15] [thresh_usd=6]
"""
import json, time, sys, threading, asyncio
import numpy as np
import websockets

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

print(f"collecting {MIN} min at 0.5s, event thresh ${THR}...")
rec=[];t0=time.time()
while time.time()-t0 < MIN*60:
    if st["cl"] and st["bin"]: rec.append((time.time(),st["cl"],st["bin"]))
    time.sleep(0.5)
print(f"samples: {len(rec)}")
t=np.array([r[0] for r in rec]);cl=np.array([r[1] for r in rec]);bn=np.array([r[2] for r in rec])
g=np.arange(t[0],t[-1],0.5);cli=np.interp(g,t,cl);bni=np.interp(g,t,bn)
# de-mean the USDT/USD offset via first-diff
dcl=np.diff(cli);dbn=np.diff(bni)
def xc(L):
    if L>0: a,b=dbn[:-L],dcl[L:]
    elif L<0: a,b=dbn[-L:],dcl[:L]
    else: a,b=dbn,dcl
    a=a-a.mean();b=b-b.mean()
    return np.corrcoef(a,b)[0,1] if len(a)>20 and a.std()>0 and b.std()>0 else 0
lags=[(round(L*0.5,1),xc(L)) for L in range(-4,50)]  # -2s..+25s in 0.5s steps
best=max(lags,key=lambda x:x[1])
print("\nXCORR peak (0.5s steps):")
for sec,c in lags:
    if c>0.03: print(f"  L={sec:+5.1f}s corr={c:+.3f} {'#'*int(c*40)}")
print(f"  => peak corr {best[1]:+.3f} at L={best[0]:+.1f}s")
# EVENT STUDY: sharp binance moves -> chainlink echo delay
bn_g=bni;cl_g=cli;n=len(g);win=8  # 8*0.5=4s window
delays=[];echoed=0;events=0
i=win
while i<n-60:
    move=bn_g[i]-bn_g[i-win]
    if abs(move)>=THR:
        events+=1
        target=cl_g[i-win]+0.5*move  # chainlink crosses half the binance move
        for j in range(i-win,min(i-win+60,n)):  # look ahead up to 30s
            if (move>0 and cl_g[j]>=target) or (move<0 and cl_g[j]<=target):
                delays.append((g[j]-g[i-win]));echoed+=1;break
        i+=win
    else: i+=1
print(f"\nEVENT STUDY: {events} sharp Binance moves (>=${THR} in 4s)")
if delays:
    d=np.array(delays)
    print(f"  Chainlink echoed {echoed}/{events} ({echoed/events*100:.0f}%)")
    print(f"  echo delay: median {np.median(d):.1f}s  mean {d.mean():.1f}s  p25 {np.percentile(d,25):.1f}s  p75 {np.percentile(d,75):.1f}s")
    print(f"  => Chainlink lags Binance by ~{np.median(d):.0f}s on sharp moves" if np.median(d)>=2 else "  => ~real-time")
else: print("  no echoes measured")
