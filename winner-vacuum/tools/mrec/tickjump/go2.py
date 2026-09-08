import mm, lw2, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}
NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    A=[lw2.run(c,*D[c],**kw) for c in mm.COINS]
    d=pd.concat(A,ignore_index=True); return lw2.score(d,lab,NB),d
print('bars',NB)
print('--- freshness gate now ACTIVE (mm.load_coin was missing evage) ---')
base=dict(QMIN=0.98,IMP=1,TL_HI=30.,TL_LO=2.,SIZE=50.,LAT=0.2,SCAN=0.4,EVMAX=1.0)
_,d0=go('BASE  QMIN.98 tl2-30 IMP+1 SIZE50',**base)
for ev in (0.3,5.0):
    go(f'  EVMAX {ev}',**{**base,'EVMAX':ev})
print()
for sz in (8,12,24,50,100,250):
    go(f'SIZE {sz}',**{**base,'SIZE':float(sz)})
print()
for sc in (0.2,0.4,1.0,2.0):
    go(f'SCAN {sc}s',**{**base,'SCAN':sc})
print()
print('--- CONTROLS ---')
go('CTRL mid-bar tick-jump (tick=0.01) tl120-290',**{**base,'QMIN':0.30,'TL_HI':290.,'TL_LO':120.})
go('CTRL mid-band .30-.96 tl2-30 (0.01 tick)',**{**base,'QMIN':0.30})
go('CTRL join the touch IMP+0',**{**base,'IMP':0})
print()
print('--- per coin / per day, BASE ---')
d0['reb']=0.2*0.07*d0.q*(1-d0.q); d0['pnl']=d0.f*((d0.win-d0.q)+d0.reb)
d0['day']=pd.to_datetime(d0.ws,unit='s',utc=True).dt.date
def agg(g):
    sh=g.f.sum(); return pd.Series({'bars':g.groupby('ws').ngroups,'sh':int(sh),
        'q':round((g.q*g.f).sum()/sh,4),'wr':round((g.win*g.f).sum()/sh,5),
        'c_sh':round(g.pnl.sum()/sh*100,3),'usd_d':round(g.pnl.sum()/6,2)})
print(d0.groupby('coin').apply(agg,include_groups=False).to_string())
print(d0.groupby('day').apply(agg,include_groups=False).to_string())
print('\n--- by tl bucket, BASE ---')
d0['tb']=pd.cut(d0.tl,[2,6,10,14,18,22,26,31],right=False)
print(d0.groupby('tb',observed=True).apply(agg,include_groups=False).to_string())
d0.to_parquet('base.parquet',index=False)
