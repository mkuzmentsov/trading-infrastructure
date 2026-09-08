import pandas as pd, numpy as np
t=pd.read_parquet('fieldctx.parquet')
t=t[t.ub.notna()]
BANDS=[0.04,0.15,0.30,0.45,0.55,0.601]; BL=['.04-.15','.15-.30','.30-.45','.45-.55','.55-.60']
t['band']=pd.cut(t.mq,BANDS,labels=BL,right=False)
M=t[(t.tl>=40)&(t.tl<=270)&(t.mq>=0.04)&(t.mq<=0.60)].copy()
def F(g):
    w=g.sz.values
    b=g.groupby(['coin','ws']).apply(lambda x: pd.Series(dict(w=x.sz.sum(),v=(x.net_c*x.sz).sum())),include_groups=False)
    W=b.w.sum(); mu=b.v.sum()/W; se=np.sqrt((((b.v-mu*b.w)**2).sum()))/W
    return pd.Series(dict(n=len(g),sh=g.sz.sum(),q=np.average(g.mq,weights=w),
        edge=np.average(g.edge_c,weights=w),sel=np.average(g.sel_c,weights=w),
        gross=np.average(g.gross_c,weights=w),reb=np.average(g.reb_c,weights=w),
        net=mu,se=se,usd_d=(g.net_c*g.sz).sum()/100/5.5))
def T(d,by,minn=2000):
    g=d.groupby(by,observed=True,dropna=False).apply(F,include_groups=False)
    return g[g.n>=minn].round(3)
