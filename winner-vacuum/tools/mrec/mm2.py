"""CHASING resting-maker simulator on the mrec v2 print tape.

Difference from mm.py: the quote is RE-PINNED whenever the market's own touch moves
(the Aug program proved re-pinning is essential: -1.52 -> -0.25 c/sh).  An order is
live from  t_run_start + LATP  to  t_run_end + LAT  where a "run" is a maximal stretch
of 10Hz snapshots over which our target price is constant; LATP = place latency,
LAT = cancel/react latency (measured live: 91ms place / 71ms cancel for openmm,
190ms median for the vacmaker fleet).

One row per (bar, side, run) = one resting order.  LONG form: every quote is a BID in
its own token's space (a U ask at A == a D bid at 1-A; the book is one book).
"""
import sys, os
import pandas as pd, numpy as np
from mm import load_coin, bidx, _lvl, COINS
TICK=0.01

def runs(coin, DELTA=0, SIZE=50.0, TL_HI=270.0, TL_LO=40.0, QLO=0.04, QHI=0.60,
         LAT=0.2, LATP=0.2, noq=False, MAXLIVE=None, s=None,t=None,res=None):
    if s is None: s,t,res=load_coin(coin)
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=bidx(s.ws.values); T=bidx(t.ws.values)
    St,Stl,Sub,Sua,Subs,Suas,Svol,Svsh,Slead,Ssp=[s[c].values for c in
        ('t','tl','ub','ua','ubs','uas','vol','volsh','lead_bps','spot')]
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]
        sel=(Stl[a:b]>=TL_LO)&(Stl[a:b]<=TL_HI)
        idx=np.nonzero(sel)[0]
        if len(idx)<3: continue
        i0,i1=a+idx[0],a+idx[-1]+1
        ub,ua=Sub[i0:i1],Sua[i0:i1]; st=St[i0:i1]; stl=Stl[i0:i1]
        ok=(ub==ub)&(ua==ua)&(ua>ub)
        ta,tb=T.get(ws,(0,0)); tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        # --- causal trailing tape flow, cumulative arrays (FLOWF)
        csell=np.cumsum(np.where(tsl,tsz,0.0)); cbuy=np.cumsum(np.where(tsl,0.0,tsz))
        def flow(t_end,W):
            j1=np.searchsorted(tt,t_end,'right'); j0=np.searchsorted(tt,t_end-W,'right')
            sv=csell[j1-1]-(csell[j0-1] if j0>0 else 0.0) if j1>0 else 0.0
            bv=cbuy[j1-1]-(cbuy[j0-1] if j0>0 else 0.0) if j1>0 else 0.0
            return sv,bv
        for side in ('U','D'):
            q=np.round((ub+DELTA*TICK) if side=='U' else (1.0-ua+DELTA*TICK),3)
            opp=ua if side=='U' else 1.0-ub
            good=ok&(q>=QLO)&(q<=QHI)&(q<opp)
            qq=np.where(good,q,np.nan)
            chg=np.ones(len(qq),bool); chg[1:]=~((qq[1:]==qq[:-1])|(np.isnan(qq[1:])&np.isnan(qq[:-1])))
            starts=np.nonzero(chg)[0]; ends=np.append(starts[1:],len(qq))
            for s0,s1 in zip(starts,ends):
                p=qq[s0]
                if p!=p: continue
                k=i0+s0
                t0=st[s0]+LATP; t1=st[s1-1]+ (LAT if s1<len(qq) else 0.0)
                if t1<=t0: continue
                if MAXLIVE and t1-t0>MAXLIVE: t1=t0+MAXLIVE
                if side=='U':
                    lp=[LBP[i][k] for i in range(3)]; ls=[LBS[i][k] for i in range(3)]
                    ourd,oppd=Subs[k],Suas[k]
                else:
                    lp=[1.0-LAP[i][k] for i in range(3)]; ls=[LAS[i][k] for i in range(3)]
                    ourd,oppd=Suas[k],Subs[k]
                ahead=0.0 if (noq or DELTA>0) else _lvl(p,lp,ls)
                j0=np.searchsorted(tt,t0,'right'); j1=np.searchsorted(tt,t1,'right')
                f=0.0; tf=np.nan; tape=0.0
                if j1>j0:
                    if side=='U': m=tsl[j0:j1]&(tp[j0:j1]<=p+1e-9)
                    else:         m=(~tsl[j0:j1])&(tp[j0:j1]>=1.0-p-1e-9)
                    if m.any():
                        z=tsz[j0:j1][m]; tape=z.sum()
                        cs=np.cumsum(z)-ahead
                        if cs[-1]>0:
                            f=min(SIZE,cs[-1]); tf=tt[j0:j1][m][int(np.argmax(cs>0))]
                midf=np.nan; mk=[np.nan]*4
                if f>0:
                    sb=St[a:b]
                    jj=np.searchsorted(sb,tf,'right')-1
                    if jj>=0:
                        m2=(Sub[a+jj]+Sua[a+jj])/2; midf=m2 if side=='U' else 1-m2
                    for z,dd in enumerate((1.0,5.0,30.0,120.0)):
                        j2=np.searchsorted(sb,tf+dd,'right')-1
                        if j2>=0 and j2<len(sb) and sb[j2]>=tf:
                            m3=(Sub[a+j2]+Sua[a+j2])/2
                            if m3==m3: mk[z]=m3 if side=='U' else 1-m3
                sv2,bv2=flow(st[s0],2.0); sv10,bv10=flow(st[s0],10.0)
                k0=max(0,s0-100); rv=np.nanstd(np.diff(np.log(np.maximum(1e-12,Ssp[i0+k0:i0+s0+1]))))*1e4 if s0>k0+3 else np.nan
                out.append((coin,ws,stl[s0],side,p,(ub[s0]+ua[s0])/2 if side=='U' else 1-(ub[s0]+ua[s0])/2,
                    round(ua[s0]-ub[s0],3),ahead,t1-t0,f,tf,midf,mk[0],mk[1],mk[2],mk[3],tape,ourd,oppd,Svol[k],Svsh[k],
                    Slead[k],sv2,bv2,sv10,bv10,rv,(wU if side=='U' else 1-wU)))
    d=pd.DataFrame(out,columns=['coin','ws','tl','side','q','mq','spr','ahead','live','f','tf',
        'midf','mk1','mk5','mk30','mk120','tape','ourdepth','oppdepth','vol','volsh','lead','sv2','bv2','sv10','bv10','rv','win'])
    if len(d):
        dt=pd.to_datetime(d.ws,unit='s',utc=True)
        d['hr']=dt.dt.hour; d['dow']=dt.dt.dayofweek; d['day']=dt.dt.date.astype(str)
    return d

def runall(**kw):
    A=[]
    for c in COINS:
        s,t,r=load_coin(c)
        if len(s)==0: continue
        A.append(runs(c,s=s,t=t,res=r,**kw))
    return pd.concat(A,ignore_index=True)

if __name__=='__main__':
    import time; t0=time.time()
    tag=sys.argv[1]
    kw=eval(sys.argv[2]) if len(sys.argv)>2 else {}
    d=runall(**kw); d.to_parquet(f'r_{tag}.parquet',index=False)
    print(tag,kw,'orders',len(d),'fills',(d.f>0).sum(),'shares %.0f'%d.f.sum(),'%.0fs'%(time.time()-t0))
