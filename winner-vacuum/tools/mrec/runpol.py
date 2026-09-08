import pandas as pd,numpy as np,pol,rep
from mm import COINS
DATA={c:pol.load_coin(c) for c in COINS}
def runcfg(**kw):
    return pd.concat([pol.sim(c,s=DATA[c][0],t=DATA[c][1],res=DATA[c][2],**kw)[0] for c in COINS],ignore_index=True)
def randpnl(R,n=12,seed=1):
    rng=np.random.default_rng(seed); o=[]
    R=R.copy(); R['day']=pd.to_datetime(R.ws,unit='s',utc=True).dt.date.astype(str)
    for i in range(n):
        w=R.groupby(['coin','day']).wU.transform(lambda x: rng.permutation(x.values))
        o.append(pol.pnl(R,wU=w).sum()/5.5)
    return np.mean(o),np.std(o)
