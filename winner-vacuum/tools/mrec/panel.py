"""Decision panel: one row per (coin, bar, tl-second) in [0,90], with the
LIVE chainlink recon estimate (respecting relay availability via cl_ts),
book state incl. top-3 ladders, and the realized outcome."""
import pandas as pd, numpy as np
import os
PQ=os.environ.get('MREC_PQ','pq')
cl=pd.read_parquet(f'{PQ}/cl.parquet')
res=pd.read_parquet(f'{PQ}/res.parquet')[['coin','ws','win']]
COLS=['coin','ws','t','tl','ua','uas','db','dbs','da','das','ub','ubs','evage','vol','volsh',
      'cl_ts','spot','lead_bps',
      'uad0p','uad0s','uad1p','uad1s','uad2p','uad2s',
      'dad0p','dad0s','dad1p','dad1s','dad2p','dad2s',
      'ubd0p','ubd0s','dbd0p','dbd0s']
s=pd.read_parquet(f'{PQ}/snapcur.parquet',columns=COLS)
s=s[(s.tl>=0)&(s.tl<=90)].copy()
s['tlk']=np.ceil(s.tl).astype(int)
s=s.sort_values(['coin','ws','tl'])
# one row per (coin,ws,tlk): the LAST snap at or below that ceiling (closest to the second mark)
s=s.groupby(['coin','ws','tlk'],observed=True).first().reset_index()
print('panel rows',len(s))

# live estimate: cumulative mean of cl over [end-62, min(end-3, cl_ts)]
frames=[]
for c,g in s.groupby('coin'):
    q=cl[cl.coin==c]
    ts=q.cl_ts.values.astype(np.int64); px=q.cl.values.astype(np.float64)
    lo,hi=ts.min(),ts.max()
    grid=np.full(hi-lo+1,np.nan); grid[ts-lo]=px
    csum=np.nancumsum(np.nan_to_num(grid)); ccnt=np.cumsum(~np.isnan(grid))
    def rng(a,b):   # mean over [a,b) with counts
        a=np.clip(np.asarray(a,dtype=np.int64)-lo,0,len(grid)); b=np.clip(np.asarray(b,dtype=np.int64)-lo,0,len(grid))
        n=ccnt[b-1]-np.where(a>0,ccnt[a-1],0)
        sm=csum[b-1]-np.where(a>0,csum[a-1],0)
        return np.where(n>0,sm/np.maximum(n,1),np.nan), n
    end=g.ws.values+300
    a=end-62; clt=np.nan_to_num(g.cl_ts.values, nan=0.0).astype(np.int64); b=np.minimum(end-3, clt+1)
    b=np.maximum(b,a+1)
    m,n=rng(a,b)
    st,_=rng(g.ws.values-62, g.ws.values-3)
    gg=g.copy()
    gg['est_bps']=(m-st)/st*1e4
    gg['obs']=n; gg['cov']=n/59.0
    gg['strike']=st
    frames.append(gg)
s=pd.concat(frames,ignore_index=True)
s=s.merge(res,on=['coin','ws'],how='inner')
s['side']=np.where(s.est_bps>0,'UP','DOWN')
s['right']=(s.side==s.win)
s['fav_ask']=np.where(s.side=='UP',s.ua,s.da)
s['fav_asz']=np.where(s.side=='UP',s.uas,s.das)
s['fav_bid']=np.where(s.side=='UP',s.ub,s.db)
s['fav_a1p']=np.where(s.side=='UP',s.uad1p,s.dad1p); s['fav_a1s']=np.where(s.side=='UP',s.uad1s,s.dad1s)
s['fav_a2p']=np.where(s.side=='UP',s.uad2p,s.dad2p); s['fav_a2s']=np.where(s.side=='UP',s.uad2s,s.dad2s)
s['day']=pd.to_datetime(s.ws,unit='s',utc=True).dt.date
s['hr']=pd.to_datetime(s.ws,unit='s',utc=True).dt.hour
s.to_parquet(f'{PQ}/panel.parquet',index=False)
print('done',s.shape)
print(s[['tlk','est_bps','cov','fav_ask','right']].describe().round(3))
