import mm, lw2, pandas as pd, sys
D={c:mm.load_coin(c) for c in mm.COINS}
NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    A=[lw2.run(c,*D[c],**kw) for c in mm.COINS]
    return lw2.score(pd.concat(A,ignore_index=True),lab,NB)
print('bars',NB)
for imp in (0,1,2,3):
    go(f'QMIN.96 tl2-30 IMP+{imp} SIZE50 LAT.2',QMIN=0.96,IMP=imp)
print()
for tlh in (20,30,45,60,90):
    go(f'QMIN.96 tl2-{tlh} IMP+1',QMIN=0.96,IMP=1,TL_HI=float(tlh))
print()
for qm in (0.90,0.95,0.96,0.97,0.98):
    go(f'QMIN{qm} tl2-30 IMP+1',QMIN=qm,IMP=1)
print()
for lat in (0.05,0.1,0.2,0.4,0.8):
    go(f'LAT {lat} QMIN.96 tl2-30 IMP+1',QMIN=0.96,IMP=1,LAT=lat)
