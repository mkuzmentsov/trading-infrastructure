"""lw3 + PERSIST gate (best bid must have been >= QMIN for >= PERSIST seconds before we quote)
   + optional SIDE restriction + returns per-bar qualifying pressure (fills with SIZE=inf)."""
import mm, pandas as pd, numpy as np
from lw3 import estmap
def run(coin,s,t,res,EM=None,MINBPS=0.0,MINCOV=0.0,PERSIST=0.0,SIDE='both',USEEST=False,
        QMIN=0.98,IMP=1,SIZE=50.,LAT=0.2,SCAN=0.4,TL_HI=30.,TL_LO=2.,EVMAX=1.0):
    if USEEST and EM is None: EM=estmap(coin)
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mm.bidx(s.ws.values); T=mm.bidx(t.ws.values)
    St,Stl,Sub,Sua,EV=s.t.values,s.tl.values,s.ub.values,s.ua.values,s.evage.values
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]; ta,tb=T.get(ws,(0,0))
        stl,st,sub,sua,ev=Stl[a:b],St[a:b],Sub[a:b],Sua[a:b],EV[a:b]
        tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        for side in ('U','D'):
            if SIDE!='both' and side!=SIDE: continue
            q=None; live=np.inf; rem=SIZE; ahead=0.0; last=-1e18; ip=0; since=None
            for j in range(len(st)):
                # persistence tracker runs on every snapshot (not only scans)
                base_all = sub[j] if side=='U' else (1.0-sua[j] if sua[j]==sua[j] else np.nan)
                if base_all==base_all and base_all>=QMIN:
                    if since is None: since=st[j]
                else: since=None
                if not (TL_LO<=stl[j]<=TL_HI): continue
                if st[j]-last<SCAN: continue
                last=st[j]
                if ev[j]==ev[j] and ev[j]>EVMAX: continue
                okest=True
                if USEEST:
                    e=EM.get((int(ws),int(round(stl[j]))))
                    okest = e is not None and e[0]==side and abs(e[1])>=MINBPS and e[2]>=MINCOV
                okp = since is not None and (st[j]-since)>=PERSIST
                ub,ua=sub[j],sua[j]
                base = ub if side=='U' else (1.0-ua if ua==ua else np.nan)
                opp  = ua if side=='U' else (1.0-ub if ub==ub else 1.0)
                tgt=None
                if okest and okp and base==base and base>=QMIN and base<0.9985:
                    tick=0.001 if base>=0.96 else 0.01
                    cand=round(base+IMP*tick,4)
                    if cand<0.9995 and not(opp==opp and cand>=opp): tgt=cand
                t_now=st[j]
                while ip<len(tt) and tt[ip]<=t_now:
                    if q is not None and rem>0 and tt[ip]>=live:
                        ok=(tsl[ip] and tp[ip]<=q+1e-9) if side=='U' else ((not tsl[ip]) and tp[ip]>=1.0-q-1e-9)
                        if ok:
                            take=tsz[ip]-ahead
                            if take>0:
                                ahead=0.0; f=min(rem,take); rem-=f
                                out.append(dict(coin=coin,ws=ws,side=side,q=q,f=f,tl=stl[j],t=tt[ip],
                                                win=(wU if side=='U' else 1-wU)))
                            else: ahead-=tsz[ip]
                    ip+=1
                if rem<=0: break
                if tgt!=q:
                    q=tgt; live=(t_now+LAT) if q is not None else np.inf; ahead=0.0
    return pd.DataFrame(out)
