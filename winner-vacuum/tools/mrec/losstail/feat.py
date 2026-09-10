"""Attach book-history features (from the 10Hz mrec tape) to REAL live fills."""
import os,numpy as np,pandas as pd
PQ='/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq'
o=pd.read_parquet('ords.parquet')
o=o[o.matched==True].copy()
o['ws']=o.bar.astype('int64')
# outcome from res
res=pd.read_parquet(f'{PQ}/res.parquet')
o=o.merge(res[['coin','ws','win']],on=['coin','ws'],how='left')
o=o[o.win.notna()].copy()
o['right']=(o.side==o.win)
o['fee']=0.07*o.avg_px*(1-o.avg_px)*o.filled
o['pnl']=np.where(o.right,o.filled-o.cost,-o.cost)-o.fee
print('live fills joined to resolutions:',len(o),o.day.min(),o.day.max(),'pnl',o.pnl.sum().round(2))

S=pd.read_parquet(f'{PQ}/snapcur.parquet',columns=['coin','ws','t','tl','ub','db','ua','da','uas','das','vol'])
S=S[(S.tl>=-5)&(S.tl<=90)]
print('snap rows',len(S))
S=S.sort_values(['coin','ws','t'])
grp={k:v for k,v in S.groupby(['coin','ws'],sort=False)}
LAGS=(3,5,6,10,20)
out={f'{p}{k}':np.full(len(o),np.nan) for k in LAGS for p in ('fb','fa','vb')}
for c in ('fb0','fa0','fbs0','tl_snap','snapn'): out[c]=np.full(len(o),np.nan)
coins=o.coin.values; wss=o.ws.values; ts=o.t.values; sides=o.side.values
for i in range(len(o)):
    g=grp.get((coins[i],wss[i]))
    if g is None: continue
    tt=g.t.values
    up=(sides[i]=='UP')
    fb=(g.ub if up else g.db).values; fa=(g.ua if up else g.da).values
    vl=g.vol.values
    j=np.searchsorted(tt,ts[i],side='right')-1     # last snap AT OR BEFORE the fire
    if j<0: continue
    out['fb0'][i]=fb[j]; out['fa0'][i]=fa[j]; out['tl_snap'][i]=g.tl.values[j]; out['snapn'][i]=len(tt)
    for k in LAGS:
        jj=np.searchsorted(tt,ts[i]-k,side='right')-1
        if jj<0: continue
        if ts[i]-k-tt[jj] > 2.0: continue        # stale lookback guard
        out[f'fb{k}'][i]=fb[jj]; out[f'fa{k}'][i]=fa[jj]; out[f'vb{k}'][i]=vl[jj]
for k,v in out.items(): o[k]=v
for k in LAGS:
    o[f'dB{k}']=o.fb0-o[f'fb{k}']
    o[f'rB{k}']=o[f'dB{k}']/o[f'fb{k}'].replace(0,np.nan)
    o[f'dA{k}']=o.fa0-o[f'fa{k}']
o['thr']=0.10+0.035*np.maximum(0,o.tl-14)
o['marg']=o.est_bps.abs()-o.thr
o.to_parquet('fills.parquet',index=False)
print('with book history:',o.fb0.notna().sum(),'of',len(o))
print(o.groupby('day').agg(n=('pnl','size'),pnl=('pnl','sum'),loss=('right',lambda s:(~s).sum())).tail(12).round(2))
