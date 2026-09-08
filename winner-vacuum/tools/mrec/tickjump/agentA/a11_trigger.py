"""What unlocks the 0.001 regime?  For every bar with fav bid >=0.98 inside tl 2-30: did fine
evidence ever appear, WHEN (vs close), and what preceded it (last print price, fav bid, time
fav bid had been >=0.96)."""
import pandas as pd, numpy as np
E=pd.read_parquet('a7_regime.parquet')
s=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','t','tl','ub','db']); s['ws']=s.ws.astype('int64')
s['fb']=np.maximum(s.ub.fillna(0),s.db.fillna(0))
q=s[(s.tl.between(2,30))&(s.fb>=0.98)].groupby(['coin','ws']).size().rename('n').reset_index()
q=q.merge(E,on=['coin','ws'],how='left')
q['fine_before_close']=q.t_fine.notna()&(q.t_fine<=q.ws+300)
q['fine_before_tl30']=q.t_fine.notna()&(q.t_fine<=q.ws+270)
print(f'bars with fav bid>=0.98 in tl 2-30: {len(q)}; fine evidence ever {q.t_fine.notna().mean()*100:.1f}%; before close {q.fine_before_close.mean()*100:.1f}%; before tl=30 {q.fine_before_tl30.mean()*100:.1f}%')
print('per coin: ever / before close / before tl30:')
print(q.groupby('coin').agg(ever=('t_fine',lambda x:round(x.notna().mean()*100,1)),bc=('fine_before_close',lambda x:round(x.mean()*100,1)),b30=('fine_before_tl30',lambda x:round(x.mean()*100,1)),n=('n','size')).to_string())
# time of first fine evidence relative to close
x=q[q.t_fine.notna()]; rel=x.t_fine-(x.ws+300)
print('t_fine - close (s): p10/25/50/75/90',np.percentile(rel,[10,25,50,75,90]).round(1))
# how long had fav bid been >=0.96 at t_fine, and fav bid then
f96=s[s.fb>=0.96].groupby(['coin','ws']).t.min().rename('t96')
x=x.merge(f96,on=['coin','ws'],how='left'); print('fav>=0.96 duration before t_fine (s): p25/50/75',np.nanpercentile(x.t_fine-x.t96,[25,50,75]).round(1))
# last trade before t_fine
t=pd.read_parquet('pq/trades.parquet',columns=['coin','ws','tok','px','side','mts']); t['ws']=t.ws.astype('int64')
t['pf']=np.where(t.tok=='U',t.px,1-t.px)  # in UP space
t=t.sort_values('mts')
m=pd.merge_asof(x[['coin','ws','t_fine']].sort_values('t_fine'),t[['coin','ws','mts','px','pf','side','tok']].rename(columns={'mts':'t_fine'}),on='t_fine',by=['coin','ws'],direction='backward',tolerance=3.0)
print('last print within 3s before t_fine: found',m.px.notna().mean().round(3),' its price (token-native) value counts:'); print(m.px.round(3).value_counts().head(8).to_string())
# bars WITHOUT fine but long time at >=0.98: how long were they at >=0.98 before close?
n=q[q.t_fine.isna()].merge(f96,on=['coin','ws'],how='left'); print('NO-fine bars: fav>=0.96 duration before close (s): p25/50/75',np.nanpercentile((n.ws+300)-n.t96,[25,50,75]).round(1))
# max fav bid in no-fine bars
mb=s[s.tl.between(0,120)].groupby(['coin','ws']).fb.max().rename('fbmax'); n=n.merge(mb,on=['coin','ws']); print('NO-fine bars: max fav bid:',n.fbmax.round(3).value_counts().head(5).to_dict())
y=x.merge(mb,on=['coin','ws']); print('fine bars: max fav bid:',y.fbmax.round(3).value_counts().head(5).to_dict())
