import pandas as pd,numpy as np
pd.set_option('display.width',250)
cl=pd.read_parquet('pq/cl.parquet'); rec=pd.read_parquet('pq/barreconL.parquet')
s=pd.read_parquet('pq/snapL.parquet',columns=['coin','dur','ws','t','tl','ua','uas','da','das','ub','ubs','db','dbs','cl_ts'])
s=s[(s.tl>=0)&(s.tl<=90)].copy(); s['tlk']=np.ceil(s.tl).astype(int)
s=s.sort_values(['coin','dur','ws','tl']).groupby(['coin','dur','ws','tlk'],observed=True).first().reset_index()
G={}
for c,g in cl.groupby('coin'):
    ts=g.cl_ts.values.astype(np.int64); px=g.cl.values.astype(np.float64)
    lo=ts.min(); grid=np.full(ts.max()-lo+1,np.nan); grid[ts-lo]=px
    G[c]=(lo,np.concatenate([[0],np.nancumsum(np.nan_to_num(grid))]),np.concatenate([[0],np.cumsum(~np.isnan(grid))]),len(grid))
s=s.merge(rec[['coin','dur','ws','end','win','strike']],on=['coin','dur','ws'],how='inner')
out=[]
for c,g in s.groupby('coin'):
    lo,cs,cn,L=G[c]
    a=np.clip((g.end.values-62-lo).astype(np.int64),0,L)
    bb=np.clip((np.minimum(g.end.values-3,np.nan_to_num(g.cl_ts.values,nan=0).astype(np.int64)+1)-lo).astype(np.int64),0,L)
    bb=np.maximum(bb,a+1)
    n=cn[bb]-cn[a]; sm=cs[bb]-cs[a]
    mean=np.where(n>0,sm/np.maximum(n,1),np.nan)
    gg=g.copy(); gg['est_bps']=(mean-g.strike.values)/g.strike.values*1e4; gg['covg']=n/59.0
    out.append(gg)
s=pd.concat(out,ignore_index=True)
s['side']=np.where(s.est_bps>0,'UP','DOWN'); s['right']=s.side==s.win
s['fav_ask']=np.where(s.side=='UP',s.ua,s.da); s['fav_asz']=np.where(s.side=='UP',s.uas,s.das)
s['fav_bid']=np.where(s.side=='UP',s.ub,s.db)
for L in (10,20):
    h=s[['coin','dur','ws','tlk','ub','db']].copy(); h['tlk']=h.tlk-L
    h=h.rename(columns={'ub':f'ub_{L}','db':f'db_{L}'})
    s=s.merge(h,on=['coin','dur','ws','tlk'],how='left')
    s[f'dB{L}']=np.where(s.side=='UP',s.ub-s[f'ub_{L}'],s.db-s[f'db_{L}'])
s['day']=pd.to_datetime(s.ws,unit='s',utc=True).dt.date
s.to_parquet('pq/panelL.parquet',index=False)
d=s[(s.tlk>=3)&(s.tlk<=20)&(s.covg>=0.5)&s.fav_ask.notna()&(s.fav_asz>=8)].copy()
d=d[d.est_bps.abs()>=(0.10+0.035*np.maximum(0,d.tlk-14))]
d=d[(d.fav_ask>=0.55)&(d.fav_ask<=0.99)]
b=d.sort_values('tlk',ascending=False).groupby(['coin','dur','ws'],as_index=False).first()
b['fee']=0.07*b.fav_ask*(1-b.fav_ask); b['ev']=b.right.astype(float)-b.fav_ask-b.fee
tot=rec.groupby(['coin','dur']).size().rename('bars_total')
g=b.groupby(['coin','dur']).apply(lambda x: pd.Series({'fireable':len(x),'ask':x.fav_ask.mean(),
    'topbook$':(x.fav_ask*x.fav_asz).median(),'win':x.right.mean(),
    'roi%':x.ev.sum()/x.fav_ask.sum()*100}),include_groups=False).join(tot)
g['hit%']=(g.fireable/g.bars_total*100).round(1)
print('=== LONG-DURATION late-window opportunity (tl 3-20, decisive, ask 0.55-0.99) ===')
print(g.round(3))
