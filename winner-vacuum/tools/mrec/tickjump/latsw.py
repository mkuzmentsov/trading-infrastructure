import mm, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}
print('published cell: q .04-.60, tl 40-270, DELTA 0, SIZE 50, join the touch, queue modelled')
print(f'{"LAT":>5} {"fills":>7} {"shares":>9} {"pub-style net":>14} {"TERMINAL net":>13} {"drift":>8}')
for lat in (0.0,0.05,0.10,0.15,0.20,0.30,0.40):
    d=pd.concat([mm.run(c,s=D[c][0],t=D[c][1],res=D[c][2],DELTA=0,SIZE=50.,H=10.,STEP=10.,
                TL_HI=270.,TL_LO=40.,QLO=0.04,QHI=0.60,LAT=lat,LATP=lat) for c in mm.COINS],
                ignore_index=True)
    f=d[d.f>0]; sh=f.f.sum(); w=lambda x:(x*f.f).sum()/sh
    reb=w(0.2*0.07*f.q*(1-f.q))
    pub=(w(f.mq-f.q)+w(f.win-f.midf)+reb)*100
    term=(w(f.win-f.q)+reb)*100
    print(f'{lat:5.2f} {len(f):7d} {int(sh):9d} {pub:+14.3f} {term:+13.3f} {w(f.midf-f.mq)*100:+8.3f}')
