import mm, lw2, lw4, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}; NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    d=pd.concat([lw4.run(c,*D[c],**kw) for c in mm.COINS],ignore_index=True); lw2.score(d,lab,NB); return d
print('bars',NB)
print('--- 1c capacity: pilot sizes ---')
for sz in (5,8,12,24,50): go(f'SIZE {sz}',SIZE=float(sz))
big=go('SIZE inf (qualifying pressure per bar)',SIZE=1e9)
pb=big.groupby(['coin','ws']).f.sum()
print('qualifying pressure per filled bar: p10 %.0f p25 %.0f p50 %.0f p75 %.0f p90 %.0f'%tuple(pb.quantile([.1,.25,.5,.75,.9])))
print('share of filled bars with >=5/8/12/24/50 sh: '+' '.join(f'{k}:{(pb>=k).mean()*100:.0f}%' for k in (5,8,12,24,50)))
print('\n--- 1e window ---')
for lo,hi in [(30,60),(30,45),(45,60),(2,60),(60,90)]: go(f'tl {lo}-{hi}',TL_LO=float(lo),TL_HI=float(hi))
print('\n--- 1f side ---')
for sd in ('U','D'): go(f'SIDE {sd} only',SIDE=sd)
print('\n--- pre-registered gates (max 2): G1 fleet est gate |bps|>=2 cov>=.5 ; G2 persistence 5s ---')
g0=go('G0 none',SIZE=50.)
g1=go('G1 |est|>=2 cov>=.5',USEEST=True,MINBPS=2.0,MINCOV=0.5)
g2=go('G2 persist>=5s',PERSIST=5.0)
g12=go('G1+G2',USEEST=True,MINBPS=2.0,MINCOV=0.5,PERSIST=5.0)
for lab,d in [('G0',g0),('G1',g1),('G2',g2),('G1+G2',g12)]:
    d.to_parquet(f'a2_{lab.replace("+","")}.parquet',index=False)
    b=d.groupby(['coin','ws']).agg(win=('win','max'),sh=('f','sum'))
    print(f'{lab:6s} filled bars {len(b)} losing bars {int((b.win==0).sum())} losing sh {int(b.sh[b.win==0].sum())}')
