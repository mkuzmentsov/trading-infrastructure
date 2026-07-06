#!/usr/bin/env python3
"""Live latency-edge monitor (MEASUREMENT ONLY, no trading). Captures, in the
last N seconds of each 5m btc bar:
  - PM RTDS Chainlink price (the resolution truth)
  - our fast aggregator (Binance + Coinbase trade WS, median)
  - the market book (leading side's ask/bid)
Then the outcome. Answers: (a) does our aggregator LEAD RTDS Chainlink? (b) is the
price-determined side UNDERPRICED in the live book at T-60/-30/-10 (executability)?
Writes jsonl to latency/monitor.jsonl.
Usage: python3 monitor.py [window_secs=90]
"""
import asyncio, json, time, sys, urllib.request
import websockets

RTDS_WS="wss://ws-live-data.polymarket.com"
BINANCE_WS="wss://stream.binance.com:9443/ws/btcusdt@trade"
COINBASE_WS="wss://ws-feed.exchange.coinbase.com"
GAMMA="https://gamma-api.polymarket.com/markets"
CLOB="https://clob.polymarket.com"
WIN=int(sys.argv[1]) if len(sys.argv)>1 else 90
OUT="every-tick-single/latency/monitor.jsonl"

def _u(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=8)

st={"chainlink":None,"chainlink_ts":0,"binance":None,"binance_ts":0,"coinbase":None,"coinbase_ts":0}

def log(ev): 
    open(OUT,"a").write(json.dumps(ev)+"\n")

async def rtds():
    sub=json.dumps({"action":"subscribe","subscriptions":[{"topic":"crypto_prices_chainlink","type":"*","filters":json.dumps({"symbol":"btc/usd"})}]})
    while True:
        try:
            async with websockets.connect(RTDS_WS,ping_interval=20) as ws:
                await ws.send(sub)
                async for m in ws:
                    try: d=json.loads(m)
                    except: continue
                    for item in (d if isinstance(d,list) else [d]):
                        pl=item.get("payload") if isinstance(item,dict) else None
                        pts=(pl or {}).get("data") if isinstance(pl,dict) else None
                        if pts:
                            v=pts[-1].get("value")
                            try: st["chainlink"]=float(v);st["chainlink_ts"]=time.time()
                            except: pass
        except Exception as e:
            await asyncio.sleep(2)

async def binance():
    while True:
        try:
            async with websockets.connect(BINANCE_WS,ping_interval=20) as ws:
                async for m in ws:
                    try: st["binance"]=float(json.loads(m)["p"]);st["binance_ts"]=time.time()
                    except: pass
        except Exception: await asyncio.sleep(2)

async def coinbase():
    sub=json.dumps({"type":"subscribe","product_ids":["BTC-USD"],"channels":["ticker"]})
    while True:
        try:
            async with websockets.connect(COINBASE_WS,ping_interval=20) as ws:
                await ws.send(sub)
                async for m in ws:
                    try:
                        d=json.loads(m)
                        if d.get("type")=="ticker" and d.get("price"): st["coinbase"]=float(d["price"]);st["coinbase_ts"]=time.time()
                    except: pass
        except Exception: await asyncio.sleep(2)

def gamma_market(ws_ts):
    try:
        slug=f"btc-updown-5m-{ws_ts}"
        d=json.loads(_u(GAMMA+f"?slug={slug}").read())
        if d: return json.loads(d[0]["clobTokenIds"])
    except Exception: pass
    return None

def book_ask_bid(token):
    try:
        d=json.loads(_u(f"{CLOB}/book?token_id={token}").read())
        asks=[float(a["price"]) for a in d.get("asks",[])]; bids=[float(b["price"]) for b in d.get("bids",[])]
        return (min(asks) if asks else None, max(bids) if bids else None)
    except Exception: return (None,None)

async def bars():
    open_px={}; toks={}; logged_outcome=set()
    while True:
        now=time.time(); cur=int(now//300)*300
        # record chainlink open for current bar
        if cur not in open_px and st["chainlink"]:
            open_px[cur]=st["chainlink"]; log({"ev":"bar_open","ws":cur,"chainlink_open":st["chainlink"],"t":round(now,2)})
        # outcome of the just-ended bar
        prev=cur-300
        if prev in open_px and prev not in logged_outcome and st["chainlink"]:
            up = st["chainlink"]>=open_px[prev]
            log({"ev":"bar_close","ws":prev,"chainlink_open":open_px[prev],"chainlink_close":st["chainlink"],"outcome":"UP" if up else "DOWN","t":round(now,2)})
            logged_outcome.add(prev)
        # in the last WIN secs, snapshot feeds + book
        secs_left=cur+300-now
        if secs_left<=WIN and cur in open_px:
            if cur not in toks: toks[cur]=gamma_market(cur)
            tk=toks.get(cur)
            o=open_px[cur]; cl=st["chainlink"]
            if tk and cl:
                lead_up = cl>=o
                ltok = tk[0] if lead_up else tk[1]
                ask,bid=book_ask_bid(ltok)
                log({"ev":"snap","ws":cur,"secs_left":round(secs_left,1),
                     "chainlink":cl,"chainlink_ts":round(st["chainlink_ts"],3),
                     "binance":st["binance"],"binance_ts":round(st["binance_ts"],3),
                     "coinbase":st["coinbase"],"coinbase_ts":round(st["coinbase_ts"],3),
                     "bar_open":o,"lead_side":"UP" if lead_up else "DOWN",
                     "lead_ask":ask,"lead_bid":bid,"t":round(now,2)})
            await asyncio.sleep(3)
        else:
            await asyncio.sleep(1)

async def main():
    print(f"latency monitor: window {WIN}s, writing {OUT}")
    await asyncio.gather(rtds(),binance(),coinbase(),bars())

if __name__=="__main__": asyncio.run(main())
