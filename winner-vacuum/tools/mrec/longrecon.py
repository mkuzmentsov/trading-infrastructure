import pandas as pd,numpy as np
pd.set_option('display.width',250)
cl=pd.read_parquet('pq/cl.parquet')
r=pd.read_parquet('pq/resL.parquet'); b=pd.read_parquet('pq/barL.parquet')
r=r.merge(b[['coin','dur','ws','end']],on=['coin','dur','ws'],how='left')
G={}
for c,g in cl.groupby('coin'):
    ts=g.cl_ts.values.astype(np.int64); px=g.cl.values.astype(np.float64)
    lo=ts.min(); grid=np.full(ts.max()-lo+1,np.nan); grid[ts-lo]=px; G[c]=(lo,grid)
def wm(c,a,b):
    lo,grid=G[c]; i0,i1=int(a-lo),int(b-lo)
    if i0<0 or i1>len(grid) or i1<=i0: return np.nan
    s=grid[i0:i1]
    return np.nanmean(s) if (~np.isnan(s)).any() else np.nan
out=[]
r=r.dropna(subset=["end"]); r["end"]=r["end"].astype("int64")
for row in r.itertuples():
    if row.coin not in G: continue
    st=wm(row.coin,row.ws-62,row.ws-3); fi=wm(row.coin,row.end-62,row.end-3)
    out.append((row.coin,row.dur,row.ws,row.end,row.win,st,fi,(fi-st)/st*1e4 if st==st and st else np.nan))
d=pd.DataFrame(out,columns=['coin','dur','ws','end','win','strike','final','margin'])
d['pred']=np.where(d.margin>0,'UP','DOWN')
ok=d.dropna(subset=['margin'])
print('=== TWAP-60 recon accuracy on longer durations ===')
print(ok.groupby('dur').apply(lambda x: pd.Series({'n':len(x),'acc':(x.pred==x.win).mean()}),include_groups=False).round(4))
print(); print(ok.groupby(['dur','coin']).apply(lambda x: pd.Series({'n':len(x),'acc':(x.pred==x.win).mean()}),include_groups=False).round(4))
d.to_parquet('pq/barreconL.parquet',index=False)
