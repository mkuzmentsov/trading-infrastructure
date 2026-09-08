import pandas as pd, numpy as np
BANDS=[0.04,0.15,0.30,0.45,0.55,0.601]; BL=['.04-.15','.15-.30','.30-.45','.45-.55','.55-.60']
def prep(d,rebmode='own'):
    d=d.copy()
    d['band']=pd.cut(d.q,BANDS,labels=BL,right=False)
    d['reb_c']=0.2*0.07*d.q*(1-d.q)*100 if rebmode=='own' else 0.198
    return d
def S(g):
    f=g[g.f>0]
    if len(f)==0: return pd.Series(dict(ord=len(g),fills=0,sh=0.0))
    wt=f.f.values
    mf=f[f.midf.notna()]
    return pd.Series(dict(
        ord=len(g), fills=len(f), sh=f.f.sum(), fillrate=len(f)/len(g),
        q=np.average(f.q,weights=wt), mq=np.average(f.mq,weights=wt),
        wr=np.average(f.win,weights=wt),
        halfspr=np.average((f.mq-f.q)*100,weights=wt),
        sel=np.average((f.win-f.mq)*100,weights=wt),
        gross=np.average((f.win-f.q)*100,weights=wt),
        reb=np.average(f.reb_c,weights=wt),
        net=np.average((f.win-f.q)*100+f.reb_c,weights=wt),
        wall=np.average((mf.q-mf.midf)*100,weights=mf.f) if len(mf) else np.nan,
        above=(mf.q>mf.midf).mean() if len(mf) else np.nan,
        usd=(((f.win-f.q)*100+f.reb_c)*f.f).sum()/100))
def tab(d,by=None,minn=200):
    if by is None: return S(d).to_frame('all').T.round(3)
    g=d.groupby(by,observed=True).apply(S,include_groups=False)
    return g[g.fills>=minn].round(3)
def rand(d,n=15,seed=0):
    """shuffle BAR outcomes within (coin,day): destroys outcome<->fill association,
       preserves the coin/day UP base rate."""
    rng=np.random.default_rng(seed)
    f=d[d.f>0].copy(); f['wU']=np.where(f.side=='U',f.win,1-f.win)
    bars=f.groupby(['coin','day','ws']).wU.first().reset_index()
    o=[]
    for i in range(n):
        b=bars.copy()
        b['w2']=b.groupby(['coin','day']).wU.transform(lambda x: rng.permutation(x.values))
        m=f.merge(b[['coin','day','ws','w2']],on=['coin','day','ws'])
        w2=np.where(m.side=='U',m.w2,1-m.w2)
        o.append(np.average((w2-m.q)*100+m.reb_c,weights=m.f))
    return np.mean(o),np.std(o)

def base_line(d):
    """market-calibration baseline over ALL quotes (fill or not): E[win]-mid."""
    return dict(n=len(d), cal=np.mean((d.win-d.mq)*100), q=d.q.mean(), mq=d.mq.mean())
def clse(d,col='netc'):
    """bar-clustered SE of the share-weighted mean of `col`."""
    f=d[d.f>0].copy()
    f['netc']=(f.win-f.q)*100+f.reb_c
    g=f.groupby(['coin','ws']).apply(lambda x: pd.Series(dict(w=x.f.sum(),v=(x.netc*x.f).sum())),include_groups=False)
    W=g.w.sum(); mu=g.v.sum()/W
    var=((g.v-mu*g.w)**2).sum()/W**2
    return mu, np.sqrt(var)

def M(g,minn=200):
    f=g[g.f>0]
    if len(f)<max(minn,1): return pd.Series(dict(fills=len(f)))
    wt=f.f.values
    r={'ord':len(g),'fills':len(f),'sh':f.f.sum(),'fr':len(f)/len(g),'q':np.average(f.q,weights=wt)}
    for c,lab in (('mk1','mo1'),('mk5','mo5'),('mk30','mo30'),('mk120','mo120')):
        m=f[f[c].notna()]
        r[lab]=np.average((m[c]-m.q)*100,weights=m.f) if len(m) else np.nan
    r['gross']=np.average((f.win-f.q)*100,weights=wt); r['reb']=np.average(f.reb_c,weights=wt)
    r['net']=r['gross']+r['reb']
    b=f.groupby(['coin','ws']).apply(lambda x: pd.Series(dict(w=x.f.sum(),v=(((x.win-x.q)*100+x.reb_c)*x.f).sum())),include_groups=False)
    W=b.w.sum(); mu=b.v.sum()/W; r['se']=np.sqrt((((b.v-mu*b.w)**2).sum()))/W
    # markout SE (low variance) on mk30
    m=f[f.mk30.notna()]
    if len(m):
        b2=m.groupby(['coin','ws']).apply(lambda x: pd.Series(dict(w=x.f.sum(),v=(((x.mk30-x.q)*100+x.reb_c)*x.f).sum())),include_groups=False)
        W2=b2.w.sum(); mu2=b2.v.sum()/W2; r['mo30net']=mu2; r['mo30se']=np.sqrt((((b2.v-mu2*b2.w)**2).sum()))/W2
    r['usd']=(((f.win-f.q)*100+f.reb_c)*f.f).sum()/100
    return pd.Series(r)
def mtab(d,by,minn=200):
    g=d.groupby(by,observed=True,dropna=False).apply(M,minn=minn,include_groups=False)
    if 'ord' in g: g=g[g.fills>=minn]
    return g.round(3)
