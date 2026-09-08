"""lw2 + the fleet's own relay-lagged TWAP recon gate (panel.est_bps/cov), so the maker
only quotes the token its own arithmetic says is winning."""
import mm, lw2, pandas as pd, numpy as np
PAN='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq/panel.parquet'
def estmap(coin):
    p=pd.read_parquet(PAN,columns=['coin','ws','tlk','est_bps','cov','side'],
                      filters=[('coin','==',coin)])
    p['estT']=np.where(p.side=='UP','U','D')
    p=p[p.tlk.between(0,95)]
    return {(int(w),int(k)):(s,e,c) for w,k,s,e,c in
            zip(p.ws,p.tlk,p.estT,p.est_bps.fillna(0.0),p['cov'].fillna(0.0))}

def run(coin,s,t,res,EM=None,MINBPS=0.5,MINCOV=0.5,**kw):
    if EM is None: EM=estmap(coin)
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mm.bidx(s.ws.values); T=mm.bidx(t.ws.values)
    A=dict(t=s.t.values,tl=s.tl.values,ub=s.ub.values,ua=s.ua.values,ubs=s.ubs.values,uas=s.uas.values)
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    EV=s.evage.values
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    QMIN=kw.get('QMIN',0.98); IMP=kw.get('IMP',1); SIZE=kw.get('SIZE',50.); LAT=kw.get('LAT',0.2)
    SCAN=kw.get('SCAN',0.4); TL_HI=kw.get('TL_HI',30.); TL_LO=kw.get('TL_LO',2.)
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]; ta,tb=T.get(ws,(0,0))
        stl,st,sub,sua=A['tl'][a:b],A['t'][a:b],A['ub'][a:b],A['ua'][a:b]
        tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        for side in ('U','D'):
            q=None; live=np.inf; rem=SIZE; ahead=0.0; last=-1e18; ip=0
            for j in range(len(st)):
                if not (TL_LO<=stl[j]<=TL_HI): continue
                if st[j]-last<SCAN: continue
                last=st[j]
                if EV[a+j]==EV[a+j] and EV[a+j]>1.0: continue
                e=EM.get((int(ws),int(round(stl[j]))))
                okest = e is not None and e[0]==side and abs(e[1])>=MINBPS and e[2]>=MINCOV
                ub,ua=sub[j],sua[j]
                base = ub if side=='U' else (1.0-ua if ua==ua else np.nan)
                opp  = ua if side=='U' else (1.0-ub if ub==ub else 1.0)
                tgt=None
                if okest and base==base and base>=QMIN and base<0.9985:
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
                                out.append(dict(coin=coin,ws=ws,side=side,q=q,f=f,tl=stl[j],
                                                win=(wU if side=='U' else 1-wU)))
                            else: ahead-=tsz[ip]
                    ip+=1
                if rem<=0: break
                if tgt!=q:
                    q=tgt; live=(t_now+LAT) if q is not None else np.inf; ahead=0.0
    return pd.DataFrame(out)
