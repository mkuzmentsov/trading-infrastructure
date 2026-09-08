"""Lead 1f: late-window wallet archetype scan.  curl (urllib gets 403 on gamma)."""
import json,subprocess,time,random,sys,pandas as pd
def get(u):
    for _ in range(3):
        try:
            r=subprocess.run(['curl','-s','--max-time','30','-A','Mozilla/5.0',u],capture_output=True,text=True,timeout=40)
            return json.loads(r.stdout)
        except Exception: time.sleep(1.2)
    return None
bar=pd.read_parquet('pq/bar.parquet'); res=pd.read_parquet('pq/res.parquet')
bar=bar.merge(res[['coin','ws','win']],on=['coin','ws']); bar=bar[bar.coin.isin(['btc','eth','sol','xrp','bnb','doge','hype'])]
N=int(sys.argv[1]) if len(sys.argv)>1 else 200
samp=bar.sample(min(N,len(bar)),random_state=1)
rows=[]
for i,r in enumerate(samp.itertuples()):
    g=get(f'https://gamma-api.polymarket.com/markets?slug={r.slug}&closed=true') or []
    if not g: g=get(f'https://gamma-api.polymarket.com/markets?slug={r.slug}') or []
    if not g: continue
    cid=g[0]['conditionId']
    d=get(f'https://data-api.polymarket.com/trades?market={cid}&limit=1000') or []
    for t in d:
        ts=t.get('timestamp',0); tl=r.ws+300-ts
        if -120<=tl<=60:
            rows.append(dict(coin=r.coin,ws=r.ws,tl=tl,w=t['proxyWallet'],side=t['side'],px=float(t['price']),sz=float(t['size']),
                             out=t.get('outcome'),win=r.win,pseud=t.get('pseudonym'),ntr=len(d)))
    if i%25==0: print(i,len(rows),flush=True)
    time.sleep(0.3)
df=pd.DataFrame(rows); df.to_parquet('wallets.parquet',index=False); print('rows',len(df),'bars',samp.shape[0])
