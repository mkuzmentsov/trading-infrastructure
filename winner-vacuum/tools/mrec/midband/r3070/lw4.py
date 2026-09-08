"""30-70c MAKER, event-driven, one order per (bar, side).  Terminal PnL.
Gates: EST (fleet's relay-lagged recon: side==token, |est_bps|>=MINBPS, cov>=MINCOV),
       MOM (mid rose by >=MOMC over the last MOMS seconds -> quote only that token),
       none.  Placement: IMP=0 join touch (queue-ahead = displayed size at level, consumed
       by prints), IMP=1 improve one 0.01 tick (ahead=0, costs 1c).  Cancel-on-touch-move
       (re-quote when the target changes).  Fill from real taker sell prints <= q."""
import mm, pandas as pd, numpy as np
PAN='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq/panel.parquet'
def estmap(coin):
    p=pd.read_parquet(PAN,columns=['coin','ws','tlk','est_bps','cov','side'],filters=[('coin','==',coin)])
    p['estT']=np.where(p.side=='UP','U','D')
    return {(int(w),int(k)):(s,e,c) for w,k,s,e,c in zip(p.ws,p.tlk,p.estT,p.est_bps.fillna(0.0),p['cov'].fillna(0.0))}

def run(coin,s,t,res,EM=None,GATE='none',MINBPS=2.0,MINCOV=0.5,MOMS=10.0,MOMC=0.02,FLIP=False,
        QMIN=0.30,QMAX=0.70,IMP=0,SIZE=50.,LAT=0.2,SCAN=0.4,TL_HI=60.,TL_LO=3.):
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mm.bidx(s.ws.values); T=mm.bidx(t.ws.values)
    St,Stl,Sub,Sua,EV=s.t.values,s.tl.values,s.ub.values,s.ua.values,s.evage.values
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]; ta,tb=T.get(ws,(0,0))
        st,stl,sub,sua,ev=St[a:b],Stl[a:b],Sub[a:b],Sua[a:b],EV[a:b]
        mid=(sub+sua)/2
        tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        for side in ('U','D'):
            q=None; live=np.inf; rem=SIZE; ahead=0.0; last=-1e18; ip=0
            for j in range(len(st)):
                if not (TL_LO<=stl[j]<=TL_HI): continue
                if st[j]-last<SCAN: continue
                last=st[j]
                if ev[j]==ev[j] and ev[j]>1.0: continue
                ok=True
                if GATE=='est':
                    e=EM.get((int(ws),int(round(stl[j]))))
                    want=(e[0] if e is not None else None)
                    if FLIP and want is not None: want=('D' if want=='U' else 'U')
                    ok = e is not None and want==side and abs(e[1])>=MINBPS and e[2]>=MINCOV
                elif GATE=='mom':
                    k=np.searchsorted(st,st[j]-MOMS)
                    d=mid[j]-mid[k] if (k<j and mid[k]==mid[k] and mid[j]==mid[j]) else 0.0
                    if FLIP: d=-d
                    ok = (d>=MOMC) if side=='U' else (d<=-MOMC)
                ub,ua=sub[j],sua[j]
                base = ub if side=='U' else (1.0-ua if ua==ua else np.nan)
                opp  = ua if side=='U' else (1.0-ub if ub==ub else 1.0)
                tgt=None
                if ok and base==base and QMIN<=base<=QMAX:
                    cand=round(base+IMP*0.01,3)
                    if not(opp==opp and cand>=opp): tgt=cand
                t_now=st[j]
                while ip<len(tt) and tt[ip]<=t_now:
                    if q is not None and rem>0 and tt[ip]>=live:
                        hit=(tsl[ip] and tp[ip]<=q+1e-9) if side=='U' else ((not tsl[ip]) and tp[ip]>=1.0-q-1e-9)
                        if hit:
                            take=tsz[ip]-ahead
                            if take>0:
                                ahead=0.0; f=min(rem,take); rem-=f
                                out.append(dict(coin=coin,ws=ws,side=side,q=q,f=f,tl=stl[j],mq=mid[j],
                                                win=(wU if side=='U' else 1-wU)))
                            else: ahead-=tsz[ip]
                    ip+=1
                if rem<=0: break
                if tgt!=q:
                    q=tgt
                    if q is None: live=np.inf; ahead=0.0
                    else:
                        live=t_now+LAT
                        if IMP>0: ahead=0.0
                        else:
                            lp=[x[j] for x in LBP] if side=='U' else [1.0-x[j] for x in LAP]
                            ls=[x[j] for x in LBS] if side=='U' else [x[j] for x in LAS]
                            ahead=mm._lvl(q,lp,ls)
    return pd.DataFrame(out)

def score(d,lab,nb):
    if not len(d): print(f'{lab:46s} NO FILLS'); return
    d=d.copy(); d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    per=d.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'),w=('win','max'))
    sh=per.s.sum(); ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    day=d.assign(day=pd.to_datetime(d.ws,unit='s',utc=True).dt.date).groupby('day').pnl.sum()
    loo=min((per.drop(index=c,level=0).p.sum()/6 for c in per.index.get_level_values(0).unique()),default=np.nan)
    print(f'{lab:46s} bars={len(per):5d} sh={int(sh):7d} q={(d.q*d.f).sum()/sh:.3f} wr={(d.win*d.f).sum()/sh:.3f} '
          f'net={ps*100:+7.2f}±{se*100:4.2f}c t={ps/se:+5.1f} $/d={per.p.sum()/6:+8.1f} d+={int((day>0).sum())}/{len(day)} '
          f'lossbars={int((per.w==0).sum())} worstLOO$/d={loo:+7.1f}')
