"""(c) deep-size liquidity provision to large sweeps, 30-70c, terminal PnL (mm.py, queue+tape cap)."""
import mm, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}
def sc(d,lab):
    f=d[d.f>0].copy(); f['pnl']=f.f*((f.win-f.q)+0.2*0.07*f.q*(1-f.q))
    per=f.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'))
    sh=per.s.sum(); ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    day=f.assign(day=pd.to_datetime(f.ws,unit='s',utc=True).dt.date).groupby('day').pnl.sum()
    big=f[f.f>=100]
    print(f'{lab:36s} fills={len(f):6d} sh={int(sh):8d} net={ps*100:+6.2f}±{se*100:4.2f}c t={ps/se:+5.1f} '
          f'$/d={per.p.sum()/6:+8.0f} d+={int((day>0).sum())}/6 | fills>=100sh: n={len(big)} net={((big.pnl.sum()/big.f.sum())*100 if len(big) else float("nan")):+6.2f}c')
for delta in (0,-1,-2,-3,-5):
    for size in (50,200):
        d=pd.concat([mm.run(c,s=D[c][0],t=D[c][1],res=D[c][2],DELTA=delta,SIZE=float(size),H=10.,STEP=10.,
                    TL_HI=290.,TL_LO=3.,QLO=0.30,QHI=0.70,LAT=0.2,LATP=0.2) for c in mm.COINS],ignore_index=True)
        sc(d,f'DELTA {delta:+d} tick  SIZE {size}')
