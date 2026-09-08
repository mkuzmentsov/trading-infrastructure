"""FULL-MAP touch-joining maker: every tl from 290 down to 2, every price band.
The program has only ever simulated q 0.04-0.60 / tl 40-270.  This lifts both caps."""
import mm, pandas as pd, numpy as np, time
t0=time.time(); A=[]
for c in mm.COINS:
    s,t,r=mm.load_coin(c)
    if not len(s): continue
    A.append(mm.run(c,s=s,t=t,res=r,DELTA=0,SIZE=50.0,H=10.0,STEP=10.0,
                    TL_HI=290.0,TL_LO=2.0,QLO=0.02,QHI=0.999,LAT=0.2,LATP=0.2))
    print(c,len(A[-1]),'%.0fs'%(time.time()-t0),flush=True)
d=pd.concat(A,ignore_index=True)
d.to_parquet('full.parquet',index=False)
print('quotes',len(d),'fills',(d.f>0).sum(),'%.0fs'%(time.time()-t0))
