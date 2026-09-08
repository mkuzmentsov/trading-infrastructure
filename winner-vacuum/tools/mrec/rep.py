import pandas as pd, numpy as np
from pol import pnl
DAYS=5.5
def summ(R,name=''):
    R=R.copy(); R['pnl']=pnl(R); R['g']=pnl(R,reb=False)
    sh=R.shU.sum()+R.shD.sum()
    n=len(R)
    se=R.pnl.std()/np.sqrt(n)*n/DAYS
    return dict(cfg=name,bars=n,sh_d=round(sh/DAYS),pair=round(((R.shU>0)&(R.shD>0)).mean(),3),
      usd_d=round(R.pnl.sum()/DAYS,1),se_d=round(se,1),
      c_sh=round(R.pnl.sum()/sh*100,3) if sh else np.nan,
      g_c_sh=round(R.g.sum()/sh*100,3) if sh else np.nan,
      reb_d=round((R.pnl.sum()-R.g.sum())/DAYS,1),
      lossbars=int((R.pnl<-0.5).sum()))
def bycoin(R):
    R=R.copy(); R['pnl']=pnl(R); R['g']=pnl(R,reb=False)
    o=[]
    for c,g in R.groupby('coin'):
        d=summ(g,c); o.append(d)
    return pd.DataFrame(o)
