import mm, lw2, lw3, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}; E={c:lw3.estmap(c) for c in mm.COINS}
NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    d=pd.concat([lw3.run(c,*D[c],EM=E[c],**kw) for c in mm.COINS],ignore_index=True)
    lw2.score(d,lab,NB); return d
print('bars',NB)
d=None
for mb in (0.0,0.5,1.0,2.0,4.0):
    x=go(f'EST gate |bps|>={mb} cov>=.5  tl2-30',MINBPS=mb)
    if mb==1.0: d=x
for tlo,thi in [(2,30),(8,30),(8,25),(3,20),(2,20)]:
    go(f'EST |bps|>=1 tl{tlo}-{thi}',MINBPS=1.0,TL_LO=float(tlo),TL_HI=float(thi))
print('\n--- ungated reference (lw2) ---')
lw2.score(pd.concat([lw2.run(c,*D[c],QMIN=0.98,IMP=1,TL_HI=30.,TL_LO=2.) for c in mm.COINS],
                    ignore_index=True),'UNGATED tl2-30',NB)
d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
d['day']=pd.to_datetime(d.ws,unit='s',utc=True).dt.date
def agg(g):
    sh=g.f.sum(); return pd.Series({'bars':g.groupby('ws').ngroups,'sh':int(sh),
      'wr':round((g.win*g.f).sum()/sh,5),'c_sh':round(g.pnl.sum()/sh*100,3),'usd_d':round(g.pnl.sum()/6,2)})
print('\nEST|bps|>=1 per coin:'); print(pd.DataFrame({c:agg(d[d.coin==c]) for c in mm.COINS if (d.coin==c).any()}).T.to_string())
print('per day:'); print(pd.DataFrame({str(k):agg(g) for k,g in d.groupby('day')}).T.to_string())
b=d.groupby(['coin','ws']).agg(pnl=('pnl','sum'),win=('win','max'))
print('losing bars',int((b.win==0).sum()),'of',len(b))
print('LOO coin $/day:',{c:round(b.drop(index=c,level=0).pnl.sum()/6,1) for c in mm.COINS if c in b.index.get_level_values(0)})
