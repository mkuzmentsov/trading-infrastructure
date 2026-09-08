import mm, pandas as pd, numpy as np
A=[]
for c in mm.COINS:
    s,t,r=mm.load_coin(c)
    A.append(mm.run(c,s=s,t=t,res=r,DELTA=0,SIZE=50.0,H=10.0,STEP=10.0,
                    TL_HI=270.0,TL_LO=40.0,QLO=0.04,QHI=0.60,LAT=0.2,LATP=0.2))
d=pd.concat(A,ignore_index=True); d.to_parquet('ctrl.parquet',index=False)
f=d[d.f>0].copy(); sh=f.f.sum()
w=lambda x:(x*f.f).sum()/sh
print('fills',len(f),'shares',int(sh),'ahead>0 share of fills',round((f.ahead>0).mean(),3))
print('share-wtd  q =',round(w(f.q),4),'  E[win] =',round(w(f.win),4),
      '  E[win-q] =',round(w(f.win-f.q)*100,3),'c')
print('rebate                       =',round(w(0.2*0.07*f.q*(1-f.q))*100,3),'c')
print('TERMINAL net                 =',round(w(f.win-f.q+0.2*0.07*f.q*(1-f.q))*100,3),'c/share')
print()
print('DECOMPOSITION of (win - q):')
print('  (a) half-spread  mid@quote - q       =',round(w(f.mq-f.q)*100,3))
print('  (b) mid DRIFT    mid@fill - mid@quote=',round(w(f.midf-f.mq)*100,3),'   <-- omitted by the published table')
print('  (c) adverse      win - mid@fill      =',round(w(f.win-f.midf)*100,3))
print('  (a)+(c)+rebate = published-style net =',round((w(f.mq-f.q)+w(f.win-f.midf)+w(0.2*0.07*f.q*(1-f.q)))*100,3))
print('  (a)+(b)+(c)+rebate = TERMINAL        =',round((w(f.mq-f.q)+w(f.midf-f.mq)+w(f.win-f.midf)+w(0.2*0.07*f.q*(1-f.q)))*100,3))
print()
print('fill price vs mid AT THE MOMENT OF FILL: q - mid@fill =',round(w(f.q-f.midf)*100,3),
      'c  (positive = we pay ABOVE the mid)')
print('$/day terminal, uncapped:',round((f.f*(f.win-f.q+0.2*0.07*f.q*(1-f.q))).sum()/6,1))
