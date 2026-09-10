import json,glob,os,pandas as pd,numpy as np
D=os.path.dirname(os.path.abspath(__file__))+'/led'
ords=[];sets=[];others={}
for f in glob.glob(D+'/*.jsonl'):
    for ln in open(f):
        ln=ln.strip()
        if not ln or not ln.startswith('{'): continue
        try: r=json.loads(ln)
        except: continue
        e=r.get('ev','')
        others[e]=others.get(e,0)+1
        if e=='PF_TE_WHALE_ORDER': ords.append(r)
        elif e=='PF_TE_LIVE_SETTLE': sets.append(r)
o=pd.DataFrame(ords); s=pd.DataFrame(sets)
print('events:',sorted(others.items(),key=lambda x:-x[1])[:25])
print('orders',o.shape,'settles',s.shape)
for d,n in ((o,'ord'),(s,'set')):
    d['day']=pd.to_datetime(d.t,unit='s',utc=True).dt.date
    print(n, d.day.min(), d.day.max())
print(o.columns.tolist()); print(s.columns.tolist())
print(o.groupby(['coin','day']).size().unstack(0).tail(14))
o.to_parquet('ords.parquet',index=False); s.to_parquet('sets.parquet',index=False)
