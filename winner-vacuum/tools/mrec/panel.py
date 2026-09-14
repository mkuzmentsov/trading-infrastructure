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
    # ⭐ 2026-09-14 FIX (a): FORWARD-FILL to match the LIVE estimator.
    # core/rtds.py window_mean() fills unpublished seconds from the last value
    # at or before them; this script used to average only the DELIVERED ticks.
    # Those are different estimators and the live one is materially better
    # (+0.91pp @tl12, +1.82pp @tl20, +5.06pp @tl60), so every gate ever
    # evaluated on panel.est_bps was scored against a WORSE signal than the
    # bot actually has. `obs`/`cov` still count REAL ticks (unchanged meaning).
    fidx=np.where(~np.isnan(grid), np.arange(len(grid)), 0)
    np.maximum.accumulate(fidx, out=fidx)
    gridf=grid[fidx]                      # leading NaNs stay NaN
    csumf=np.nancumsum(np.nan_to_num(gridf)); chas=np.cumsum(~np.isnan(gridf))
    ccnt=np.cumsum(~np.isnan(grid))       # REAL ticks, for obs/cov
    def rng(a,b):   # forward-filled mean over [a,b), + real-tick count
        a=np.clip(np.asarray(a,dtype=np.int64)-lo,0,len(grid)); b=np.clip(np.asarray(b,dtype=np.int64)-lo,0,len(grid))
        n=ccnt[b-1]-np.where(a>0,ccnt[a-1],0)                   # real ticks
        nf=chas[b-1]-np.where(a>0,chas[a-1],0)                  # filled seconds
        sm=csumf[b-1]-np.where(a>0,csumf[a-1],0)
        return np.where(nf>0,sm/np.maximum(nf,1),np.nan), n
    end=g.ws.values+300
    a=end-62; clt=np.nan_to_num(g.cl_ts.values, nan=0.0).astype(np.int64); b=np.minimum(end-3, clt+1)
    # ⭐ 2026-09-14 FIX (b): LOOK-AHEAD. The old `b=np.maximum(b,a+1)` clamp
    # forced the window open even when the relay had not yet reached its start
    # (cl_ts < end-62), so the row silently averaged a tick from the FUTURE:
    # 100% of rows at tlk>=63 read a future tick (median +1s, up to +28s).
    # A decision made before the settlement window opens has NO estimate —
    # emit NaN rather than a clairvoyant one.
    started = clt + 1 > a
    b=np.maximum(b,a+1)
    m,n=rng(a,b)
    m=np.where(started, m, np.nan); n=np.where(started, n, 0)
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
