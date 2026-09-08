import pandas as pd, json, numpy as np
rows=[]
for l in open('tick_raw.jsonl'):
    try: d=json.loads(l); m=d['m']
    except Exception: continue
    rows.append(dict(t=d['t'],ws=d['ws'],tok=d['tok'],old=m.get('old_tick_size'),new=m.get('new_tick_size'),vts=int(m.get('timestamp',0))/1000,aid=m.get('asset_id')))
d=pd.DataFrame(rows)
bar=pd.read_parquet('pq/bar.parquet'); up=bar.set_index('up').coin.to_dict(); dn=bar.set_index('down').coin.to_dict()
d['coin']=d.aid.map(lambda a: up.get(a) or dn.get(a)); d=d[d.coin.notna()]
d=d.drop_duplicates(['coin','ws','tok','new','vts'])
print(d.groupby(['old','new']).size().to_string())
fine=d[d.new=='0.001'].groupby(['coin','ws']).agg(t_tick=('vts','min'),t_rx=('t','min'),n=('t','size')).reset_index()
fine['ws']=fine.ws.astype('int64'); fine['rel']=fine.t_tick-(fine.ws+300)
print('bars with a 0.01->0.001 flip:',len(fine),'per coin',fine.groupby('coin').size().to_dict())
print('venue-ts of flip minus close (s): p10/25/50/75/90',np.percentile(fine.rel,[10,25,50,75,90]).round(1))
print('flip BEFORE close:',(fine.rel<0).mean().round(3),' before tl=30:',(fine.rel<-30).mean().round(3),' before tl=60:',(fine.rel<-60).mean().round(3),' before tl=120:',(fine.rel<-120).mean().round(3))
print('recorder receive lag (s) p50/90:',np.percentile(fine.t_rx-fine.t_tick,[50,90]).round(2))
fine.to_parquet('a12_tick.parquet',index=False)
t=pd.read_parquet('pq/trades.parquet',columns=['coin','ws','tok','px','sz','side','mts']); t['ws']=t.ws.astype('int64'); t['pU']=np.where(t.tok=='U',t.px,1-t.px); t=t.sort_values('mts')
m=pd.merge_asof(fine.sort_values('t_tick'),t.rename(columns={'mts':'t_tick'})[['coin','ws','t_tick','px','pU','side','tok']],on='t_tick',by=['coin','ws'],direction='backward',tolerance=1.0)
print('last print <=1s before the flip: found',m.px.notna().mean().round(3),'; fav-space price:',np.maximum(m.pU,1-m.pU).round(3).value_counts().head(6).to_dict())
# first print >0.96 in fav space before flip
t['fp']=np.maximum(t.pU,1-t.pU); f96=t[t.fp>0.9605].groupby(['coin','ws']).mts.min().rename('t_p96')
x=fine.merge(f96,on=['coin','ws'],how='left'); print('flip minus first print >0.96 (s): found',x.t_p96.notna().mean().round(3),' p10/50/90',np.nanpercentile(x.t_tick-x.t_p96,[10,50,90]).round(1))
s=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','t','ub','db','ua','da']); s['ws']=s.ws.astype('int64'); s=s.sort_values('t')
m3=pd.merge_asof(fine.sort_values('t_tick'),s.rename(columns={'t':'t_tick'}),on='t_tick',by=['coin','ws'],direction='backward',tolerance=5.0)
fb=np.maximum(m3.ub.fillna(0),m3.db.fillna(0)); fa=pd.Series(np.where(m3.ub.fillna(0)>=m3.db.fillna(0),m3.ua,m3.da))
print('fav BID at flip:',pd.Series(fb).round(3).value_counts().head(5).to_dict(),' fav ASK at flip:',fa.round(3).value_counts(dropna=False).head(5).to_dict())
mid=(fb+fa.fillna(1.0))/2; print('fav MID at flip p10/50/90',np.nanpercentile(mid,[10,50,90]).round(4))
# first time fav bid>=0.96 / mid>=0.96 before flip
s['fb']=np.maximum(s.ub.fillna(0),s.db.fillna(0)); s['fa']=np.where(s.ub.fillna(0)>=s.db.fillna(0),s.ua,s.da); s['mid']=(s.fb+pd.Series(s.fa).fillna(1.0).values)/2
b96=s[s.fb>=0.96].groupby(['coin','ws']).t.min().rename('t_b96'); m96=s[s.mid>=0.96].groupby(['coin','ws']).t.min().rename('t_m96')
x=fine.merge(b96,on=['coin','ws'],how='left').merge(m96,on=['coin','ws'],how='left')
print('flip minus first fav BID>=0.96 (s): p10/50/90',np.nanpercentile(x.t_tick-x.t_b96,[10,50,90]).round(1),'  minus first MID>=0.96:',np.nanpercentile(x.t_tick-x.t_m96,[10,50,90]).round(1))
# coverage vs qualifying bars (fav bid >=0.98 in tl 2-30)
q=s[(s.t>=s.ws+270)&(s.t<=s.ws+298)&(s.fb>=0.98)].groupby(['coin','ws']).size().rename('n').reset_index()
q=q.merge(fine[['coin','ws','t_tick']],on=['coin','ws'],how='left')
print(f'\nqualifying bars {len(q)}: flip ever {q.t_tick.notna().mean()*100:.1f}%  flip before tl30 {(q.t_tick<q.ws+270).mean()*100:.1f}%  before tl60 {(q.t_tick<q.ws+240).mean()*100:.1f}%')
print(q.assign(b30=q.t_tick<q.ws+270,ev=q.t_tick.notna()).groupby('coin').agg(n=('n','size'),ever=('ev','mean'),b30=('b30','mean')).round(3).to_string())
