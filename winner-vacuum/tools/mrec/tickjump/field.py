"""HIGH-POWER version of the tick-jump edge: score EVERY late-window taker sell print that
would have hit an improver's bid.  Same quantity as lw2, 40x the sample (no 50sh/bar cap)."""
import mm, pandas as pd, numpy as np
A=[]
for c in mm.COINS:
    s,t,res=mm.load_coin(c)
    s2=s[['ws','t','tl','ub','ua','evage']].astype({'ws':'int64'}).sort_values('t')
    t2=t[['ws','t','pU','sz','sellp']].astype({'ws':'int64'}).sort_values('t')
    m=pd.merge_asof(t2,s2,on='t',by='ws',direction='backward',tolerance=1.0)
    m=m[m.tl.between(2,30)&(m.evage<1.0)]
    m['bb']=np.where(m.sellp,m.ub,1.0-m.ua)
    m['pp']=np.where(m.sellp,m.pU,1.0-m.pU)
    r=res.set_index('ws').win.to_dict()
    wU=m.ws.map(r).eq('UP').astype(int)
    m['win']=np.where(m.sellp,wU,1-wU)               # sell pressure on U -> we buy U
    m=m[(m.bb>=0.98)&(m.bb<0.9985)&m.bb.notna()&(m.pp<=m.bb+1e-9)]
    m['q']=np.round(m.bb+0.001,4); m['coin']=c
    A.append(m[['coin','ws','tl','q','sz','win']])
    print(' ',c,len(A[-1]),flush=True)
d=pd.concat(A,ignore_index=True)
d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.sz*((d.win-d.q)+d.reb)
d['day']=pd.to_datetime(d.ws,unit='s',utc=True).dt.date
def agg(g):
    sh=g.sz.sum(); per=g.groupby(['ws']).agg(p=('pnl','sum'),s=('sz','sum'))
    ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    return pd.Series({'prints':len(g),'bars':per.shape[0],'sh':int(sh),'q':round((g.q*g.sz).sum()/sh,4),
        'wr':round((g.win*g.sz).sum()/sh,5),'c_sh':round(ps*100,3),'se':round(se*100,3),
        't':round(ps/se,2),'usd_d':round(g.pnl.sum()/6,1)})
print('\n=== ALL (upper bound: we intercept every such print) ===')
print(agg(d).to_string())
print('\n=== per coin ===')
print(pd.DataFrame({c:agg(d[d.coin==c]) for c in mm.COINS}).T.to_string())
print('\n=== per day  ===')
print(pd.DataFrame({str(k):agg(g) for k,g in d.groupby('day')}).T.to_string())
print('\n=== per tl   ===')
d['tb']=pd.cut(d.tl,[2,8,14,20,26,31],right=False)
print(pd.DataFrame({str(k):agg(g) for k,g in d.groupby('tb',observed=True)}).T.to_string())
print('\n=== leave-one-coin-out c/share ===')
for c in mm.COINS:
    x=d[d.coin!=c]; print(f'  drop {c:5s} -> {(x.pnl.sum()/x.sz.sum())*100:+7.3f} c/sh  ${x.pnl.sum()/6:+8.1f}/d')
L=d[d.win==0]
print(f'\nlosing prints {len(L)} shares {int(L.sz.sum())} ({L.sz.sum()/d.sz.sum()*100:.3f}%) '
      f'break-even loss rate {(1-(d.q*d.sz).sum()/d.sz.sum())*100:.3f}%')
print('losing bars', L.groupby(['coin','ws']).ngroups, 'of', d.groupby(['coin','ws']).ngroups)
