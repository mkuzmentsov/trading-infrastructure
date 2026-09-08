"""Lead 3: terminal re-score of the two 'not refuted' rebate-farm cells."""
import mm, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}
def score(d,lab):
    f=d[d.f>0].copy(); sh=f.f.sum(); w=lambda x:(x*f.f).sum()/sh
    reb=w(0.2*0.07*f.q*(1-f.q))
    per=f.assign(p=f.f*((f.win-f.q)+0.2*0.07*f.q*(1-f.q))).groupby(['coin','ws']).agg(p=('p','sum'),s=('f','sum'))
    ps=per.p.sum()/per.s.sum(); se=np.sqrt(((per.p-ps*per.s)**2).sum())/per.s.sum()
    day=f.assign(p=f.f*((f.win-f.q)+0.2*0.07*f.q*(1-f.q)),day=pd.to_datetime(f.ws,unit='s',utc=True).dt.date).groupby('day').p.sum()
    print(f'{lab:52s} fills={len(f):6d} sh={int(sh):8d} half-spread {w(f.mq-f.q)*100:+.3f} drift {w(f.midf-f.mq)*100:+.3f} adverse {w(f.win-f.midf)*100:+.3f} reb {reb*100:+.3f} | pub-style {(w(f.mq-f.q)+w(f.win-f.midf)+reb)*100:+.3f} | TERMINAL {ps*100:+.3f} +/- {se*100:.3f} c/sh  $/d {per.p.sum()/6:+.1f} d+={int((day>0).sum())}/{len(day)}')
# (a) §7 cell: two-sided touch, q .45-.60, spread<=2c, first 60s (tl 240-300), leave both
d=pd.concat([mm.run(c,s=D[c][0],t=D[c][1],res=D[c][2],DELTA=0,SIZE=50.,H=10.,STEP=10.,TL_HI=295.,TL_LO=240.,QLO=0.45,QHI=0.60,LATP=0.15) for c in mm.COINS],ignore_index=True)
score(d[d.spr<=0.021],'(a) §7 two-sided touch .45-.60 spr<=2c tl240-295 LAT.15')
score(d,'(a) same, any spread')
d=pd.concat([mm.run(c,s=D[c][0],t=D[c][1],res=D[c][2],DELTA=0,SIZE=50.,H=10.,STEP=10.,TL_HI=295.,TL_LO=240.,QLO=0.45,QHI=0.60,LATP=0.20) for c in mm.COINS],ignore_index=True)
score(d[d.spr<=0.021],'(a) same LAT.20')
# (b) cheap band .04-.15, tl 40-270
d=pd.concat([mm.run(c,s=D[c][0],t=D[c][1],res=D[c][2],DELTA=0,SIZE=50.,H=10.,STEP=10.,TL_HI=270.,TL_LO=40.,QLO=0.04,QHI=0.15,LATP=0.20) for c in mm.COINS],ignore_index=True)
score(d,'(b) cheap band .04-.15 tl40-270 LAT.20')
score(d[d.q<=0.08],'(b) .04-.08')
score(d[d.q>0.08],'(b) .08-.15')
