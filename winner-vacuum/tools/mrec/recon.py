import pandas as pd, numpy as np
PQ='pq'
cl=pd.read_parquet(f'{PQ}/cl.parquet')
res=pd.read_parquet(f'{PQ}/res.parquet')
out=[]
for c,g in cl.groupby('coin'):
    ts=g.cl_ts.values.astype(np.int64); px=g.cl.values.astype(np.float64)
    lo,hi=ts.min(),ts.max()
    grid=np.full(hi-lo+1,np.nan); grid[ts-lo]=px
    r=res[res.coin==c]
    for ws,win in zip(r.ws.values, r.win.values):
        end=ws+300
        def wm(a,b):
            i0,i1=a-lo,b-lo
            if i0<0 or i1>len(grid): return np.nan,0,b-a
            s=grid[i0:i1]; o=~np.isnan(s)
            return (np.nanmean(s) if o.any() else np.nan), int(o.sum()), len(s)
        st,so,stot=wm(ws-62,ws-3)
        fi,fo,ftot=wm(end-62,end-3)
        out.append((c,ws,win,st,so,fi,fo,(fi-st)/st*1e4 if st and st==st else np.nan))
d=pd.DataFrame(out,columns=['coin','ws','win','strike','sobs','final','fobs','margin_bps'])
d['pred']=np.where(d.margin_bps>0,'UP','DOWN')
d.to_parquet(f'{PQ}/barrecon.parquet',index=False)
ok=d.dropna(subset=['margin_bps'])
print('bars',len(d),'with recon',len(ok))
print('overall recon accuracy:',(ok.pred==ok.win).mean().round(4))
ok=ok.copy(); ok['ab']=pd.cut(ok.margin_bps.abs(),[0,.1,.25,.5,1,2,5,1e9])
print(ok.groupby('ab',observed=True).apply(lambda x: pd.Series({'n':len(x),'acc':(x.pred==x.win).mean()}),include_groups=False).round(4))
print(); print('per coin acc'); print(ok.groupby('coin').apply(lambda x: pd.Series({'n':len(x),'acc':(x.pred==x.win).mean()}),include_groups=False).round(4))
