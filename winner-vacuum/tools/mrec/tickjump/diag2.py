"""Do real SELL prints execute above the recorded best bid?  merge_asof per (coin,ws)."""
import mm, pandas as pd, numpy as np
A=[]
for c in mm.COINS:
    s,t,res=mm.load_coin(c)
    s2=s[['ws','t','tl','ub','ua','evage']].astype({'ws':'int64'}).sort_values('t')
    t2=t[['ws','t','pU','sz','sellp']].astype({'ws':'int64'}).sort_values('t')
    m=pd.merge_asof(t2,s2,on='t',by='ws',direction='backward',tolerance=1.0)
    m=m[m.tl.between(2,30)]
    m['bb']=np.where(m.sellp,m.ub,1.0-m.ua)          # best bid in the pressured token's space
    m['pp']=np.where(m.sellp,m.pU,1.0-m.pU)          # print price in that space
    m=m[(m.bb>=0.96)&m.bb.notna()&(m.evage<1.0)]
    m['dp']=m.pp-m.bb; m['coin']=c
    A.append(m[['coin','ws','dp','sz','bb','pp']])
    print(' ',c,len(A[-1]),flush=True)
d=pd.concat(A,ignore_index=True)
print('\nn prints',len(d),'shares',int(d.sz.sum()))
for lab,f in [('print px > best bid  (someone had improved)',d.dp>1e-6),
              ('print px == best bid (we would have been the improver)',abs(d.dp)<=1e-6),
              ('print px < best bid  (walked down through us)',d.dp<-1e-6)]:
    print(f'  {lab:56s} prints {f.mean()*100:6.2f}%   shares {d.sz[f].sum()/d.sz.sum()*100:6.2f}%')
p=d[d.dp>1e-6]
print('\n improvement size, in 0.001 ticks (share-weighted):')
print(p.assign(k=np.round(p.dp*1000)).groupby('k').sz.sum().sort_index().head(10).to_string())
