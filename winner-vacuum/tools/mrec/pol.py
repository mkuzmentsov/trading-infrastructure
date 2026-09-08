"""Bar-level POLICY simulator: two-sided chasing maker with cancel-on-fill,
per-side share cap, optional taker stop-loss.  Real print tape, FIFO queue,
tape-size cap.  One row per (bar, coin).

Sides are named in own-token space: 'U' = bid on UP at q, 'D' = bid on DOWN at q
(== an ask on UP at 1-q).  A paired share (one U + one D) settles at $1.
"""
import sys, os
import pandas as pd, numpy as np
from mm import load_coin, bidx, _lvl, COINS
TICK=0.01

def sim(coin, DELTA=0, CAP=50.0, TL_HI=270.0, TL_LO=40.0, QLO=0.04, QHI=0.60,
        LAT=0.2, LATP=0.2, noq=False, cancel_other=True, standdown=True, SPRMAX=None, TLMIN=None,
        STOP=None, STOPTAPE=True, s=None,t=None,res=None, veto=None):
    if s is None: s,t,res=load_coin(coin)
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=bidx(s.ws.values); T=bidx(t.ws.values)
    St,Stl,Sub,Sua,Subs,Suas,Svol,Svsh,Slead=[s[c].values for c in
        ('t','tl','ub','ua','ubs','uas','vol','volsh','lead_bps')]
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    rows=[]; fills=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]
        sel=(Stl[a:b]>=TL_LO)&(Stl[a:b]<=TL_HI); idx=np.nonzero(sel)[0]
        if len(idx)<3: continue
        i0,i1=a+idx[0],a+idx[-1]+1
        ub,ua,st=Sub[i0:i1],Sua[i0:i1],St[i0:i1]
        ok=(ub==ub)&(ua==ua)&(ua>ub)
        ta,tb=T.get(ws,(0,0)); tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        # ---- build runs per side
        R={}
        for side in ('U','D'):
            q=np.round((ub+DELTA*TICK) if side=='U' else (1.0-ua+DELTA*TICK),3)
            opp=ua if side=='U' else 1.0-ub
            good=ok&(q>=QLO)&(q<=QHI)&(q<opp)
            if SPRMAX is not None: good=good&((ua-ub)<=SPRMAX+1e-9)
            if veto is not None: good=good&veto(side,i0,i1,s)
            qq=np.where(good,q,np.nan)
            chg=np.ones(len(qq),bool); chg[1:]=~((qq[1:]==qq[:-1])|(np.isnan(qq[1:])&np.isnan(qq[:-1])))
            starts=np.nonzero(chg)[0]; ends=np.append(starts[1:],len(qq))
            L=[]
            for s0,s1 in zip(starts,ends):
                p=qq[s0]
                if p!=p: continue
                k=i0+s0
                if side=='U': lp=[LBP[i][k] for i in range(3)]; ls=[LBS[i][k] for i in range(3)]
                else:         lp=[1.0-LAP[i][k] for i in range(3)]; ls=[LAS[i][k] for i in range(3)]
                ah=0.0 if (noq or DELTA>0) else _lvl(p,lp,ls)
                t0=st[s0]+LATP; t1=st[s1-1]+(LAT if s1<len(qq) else 0.0)
                if t1<=t0: continue
                L.append((t0,t1,p,ah))
            R[side]=L
        # ---- event walk over prints
        stt={sd:dict(ri=0,cons=0.0,cur=None,sh=0.0,notl=0.0,dead=-1.0,first=np.nan,last=np.nan,ev=[]) for sd in ('U','D')}
        for pi in range(len(tt)):
            tau=tt[pi]; pxu=tp[pi]; sz=tsz[pi]; isell=tsl[pi]
            for side in ('U','D'):
                S_=stt[side]
                if S_['sh']>=CAP or tau<S_['dead']: continue
                L=R[side]
                while S_['ri']<len(L) and L[S_['ri']][1]<tau: S_['ri']+=1; S_['cur']=None; S_['cons']=0.0
                if S_['ri']>=len(L): continue
                t0,t1,p,ah=L[S_['ri']]
                if tau<t0: continue
                if S_['cur']!=S_['ri']: S_['cur']=S_['ri']; S_['cons']=0.0
                hit = (isell and pxu<=p+1e-9) if side=='U' else ((not isell) and pxu>=1.0-p-1e-9)
                if not hit: continue
                prev=max(0.0,S_['cons']-ah); S_['cons']+=sz; now=max(0.0,S_['cons']-ah)
                add=min(now-prev, CAP-S_['sh'])
                if add<=0: continue
                S_['sh']+=add; S_['notl']+=add*p
                if S_['first']!=S_['first']: S_['first']=tau
                S_['last']=tau
                fills.append((coin,ws,side,tau,p,add,(wU if side=='U' else 1-wU)))
                S_['ev'].append((tau,add))
                if cancel_other:
                    o='D' if side=='U' else 'U'
                    stt[o]['dead']= 1e18 if standdown else tau+LAT
        u,d=stt['U'],stt['D']
        pair=min(u['sh'],d['sh'])
        # ---- taker stop-loss on the UNPAIRED leg, STOP seconds after its first fill
        exU=exD=0.0; exPU=exPD=np.nan
        if STOP is not None:
            for side,S_ in (('U',u),('D',d)):
                other=d if side=='U' else u
                if S_['first']!=S_['first']: continue
                te=S_['first']+STOP
                held=sum(z for tt_,z in S_['ev'] if tt_<=te)
                heldo=sum(z for tt_,z in other['ev'] if tt_<=te)
                unp=held-heldo                      # CAUSAL: unpaired as of te, no look-ahead
                if unp<=0: continue
                jj=np.searchsorted(St[a:b],te,'right')-1
                if jj<0 or jj>=b-a: continue
                kk=a+jj
                px = Sub[kk] if side=='U' else 1.0-Sua[kk]     # we SELL at the best bid in own space
                if px!=px: continue
                if STOPTAPE:
                    j0=np.searchsorted(tt,te,'right'); j1=np.searchsorted(tt,te+1.5,'right')
                    if j1<=j0: continue
                    if side=='U': mm=tsl[j0:j1]&(tp[j0:j1]<=px+1e-9)
                    else:         mm=(~tsl[j0:j1])&(tp[j0:j1]>=1.0-px-1e-9)
                    if not mm.any(): continue
                    unp=min(unp,tsz[j0:j1][mm].sum())
                    pp=tp[j0:j1][mm]
                    px=float(pp[0]) if side=='U' else float(1.0-pp[0])   # fill at the PRINT price
                if side=='U': exU,exPU=unp,px
                else:         exD,exPD=unp,px
        rows.append((coin,ws,wU,u['sh'],u['notl'],d['sh'],d['notl'],pair,u['first'],d['first'],
                     exU,exPU,exD,exPD))
    R=pd.DataFrame(rows,columns=['coin','ws','wU','shU','notlU','shD','notlD','pair','tfU','tfD','exU','exPU','exD','exPD'])
    F=pd.DataFrame(fills,columns=['coin','ws','side','tf','q','sz','win'])
    return R,F

def pnl(R,reb=True,wU=None):
    w=R.wU if wU is None else wU
    g=(w*R.shU-R.notlU)+((1-w)*R.shD-R.notlD)
    if 'exU' in R:
        for side,ex,exp,wn in (('U',R.exU,R.exPU,w),('D',R.exD,R.exPD,1-w)):
            e=ex.fillna(0); p=exp.fillna(0)
            g=g+e*(p-wn)-e*0.07*p*(1-p)      # unwind the settled leg at p, pay taker fee
    r=0.2*0.07*((R.notlU/R.shU.replace(0,np.nan)).fillna(0)*(1-(R.notlU/R.shU.replace(0,np.nan)).fillna(0))*R.shU
              +(R.notlD/R.shD.replace(0,np.nan)).fillna(0)*(1-(R.notlD/R.shD.replace(0,np.nan)).fillna(0))*R.shD) if reb else 0
    return g+r

if __name__=='__main__':
    tag=sys.argv[1]; kw=eval(sys.argv[2]) if len(sys.argv)>2 else {}
    A=[];B=[]
    for c in COINS:
        s,t,r=load_coin(c)
        if len(s)==0: continue
        R,F=sim(c,s=s,t=t,res=r,**kw); A.append(R); B.append(F)
    R=pd.concat(A,ignore_index=True); F=pd.concat(B,ignore_index=True)
    R.to_parquet(f'p_{tag}.parquet',index=False); F.to_parquet(f'pf_{tag}.parquet',index=False)
    R['pnl']=pnl(R)
    print(tag,kw,'bars',len(R),'pnl $%.1f  $/day %.1f  shares %.0f  pairrate %.3f'%(
        R.pnl.sum(),R.pnl.sum()/5.5,R.shU.sum()+R.shD.sum(),((R.shU>0)&(R.shD>0)).mean()))
