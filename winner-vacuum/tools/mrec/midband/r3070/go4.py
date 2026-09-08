import mm, lw4, pandas as pd
D={c:mm.load_coin(c) for c in mm.COINS}; E={c:lw4.estmap(c) for c in mm.COINS}
NB=sum(len(set(D[c][0].ws)) for c in mm.COINS)
def go(lab,**kw):
    lw4.score(pd.concat([lw4.run(c,*D[c],EM=E[c],**kw) for c in mm.COINS],ignore_index=True),lab,NB)
print('=== A. TWAP-recon-gated maker, band 0.30-0.70, tl 3-60, join touch (queue) ===')
go('ungated two-sided (reference)',GATE='none')
for mb in (1,2,3,5,8):
    go(f'EST |bps|>={mb} cov>=.5',GATE='est',MINBPS=mb)
go('PLACEBO est side FLIPPED |bps|>=3',GATE='est',MINBPS=3,FLIP=True)
go('EST |bps|>=3 improve +1c',GATE='est',MINBPS=3,IMP=1)
go('EST |bps|>=3 tl 3-30',GATE='est',MINBPS=3,TL_HI=30.)
go('EST |bps|>=3 band .40-.60',GATE='est',MINBPS=3,QMIN=0.40,QMAX=0.60)
print('=== B. momentum-following one-sided maker, band 0.30-0.70, full bar (tl 3-290) ===')
for ms,mc in [(5,0.01),(10,0.02),(20,0.03),(30,0.05)]:
    go(f'MOM mid up >={mc*100:.0f}c in {ms}s',GATE='mom',MOMS=ms,MOMC=mc,TL_HI=290.)
go('PLACEBO MOM flipped (contrarian) 10s/2c',GATE='mom',MOMS=10,MOMC=0.02,FLIP=True,TL_HI=290.)
go('ungated two-sided full bar (reference)',GATE='none',TL_HI=290.)
