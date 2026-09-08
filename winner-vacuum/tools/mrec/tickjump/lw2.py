"""TICK-JUMP MAKER, event-driven, ONE maintained order per bar (no window double-count).

Policy: while tl in [TL_LO,TL_HI] and the chosen token's best bid >= QMIN, keep a post-only
bid at best_bid + IMP ticks (tick = 0.001 above 0.96, else 0.01).  Re-quote only when the
target price changes; a new order is live only after LAT.  Fill from REAL taker sell prints
at <= q (our own token space).  Budget = SIZE shares per bar.  Hold to settlement.
ahead = 0 when IMP>0 (improving over the best bid creates an empty level by construction);
        displayed size at the level when IMP==0.
"""
import mm, pandas as pd, numpy as np, sys
def bar_run(stl,st,sub,sua,subs,suas,lbp,lbs,lap,las,evg,
            tt,tp,tsz,tsl,wU,TL_HI,TL_LO,QMIN,IMP,SIZE,LAT,SCAN,EVMAX,SIDE):
    """returns list of fill dicts"""
    fills=[]
    for side in ('U','D'):
        if SIDE!='both' and side!=SIDE: continue
        q=None; live=np.inf; rem=SIZE; ahead=0.0; nq=0
        last_scan=-1e18
        ip=0; n=len(st)
        for j in range(n):
            if not (TL_LO<=stl[j]<=TL_HI): continue
            if st[j]-last_scan<SCAN: continue
            last_scan=st[j]
            if evg[j]==evg[j] and evg[j]>EVMAX: continue
            ub,ua=sub[j],sua[j]
            base = ub if side=='U' else (1.0-ua if ua==ua else np.nan)
            opp  = ua if side=='U' else (1.0-ub if ub==ub else 1.0)
            tgt=None
            if base==base and base>=QMIN and base<0.9985:
                tick=0.001 if base>=0.96 else 0.01
                cand=round(base+IMP*tick,4)
                if cand<0.9995 and not(opp==opp and cand>=opp): tgt=cand
            # process prints since previous snapshot against the CURRENT resting order
            t_now=st[j]
            while ip<len(tt) and tt[ip]<=t_now:
                if q is not None and rem>0 and tt[ip]>=live:
                    ok=(tsl[ip] and tp[ip]<=q+1e-9) if side=='U' else ((not tsl[ip]) and tp[ip]>=1.0-q-1e-9)
                    if ok:
                        take=tsz[ip]-ahead
                        if take>0:
                            ahead=0.0; f=min(rem,take); rem-=f
                            fills.append(dict(side=side,q=q,f=f,tl=stl[j],win=(wU if side=='U' else 1-wU)))
                        else: ahead-=tsz[ip]
                ip+=1
            if rem<=0: break
            if tgt!=q:
                q=tgt; nq+=1
                if q is None: live=np.inf; ahead=0.0
                else:
                    live=t_now+LAT
                    if IMP>0: ahead=0.0
                    else:
                        lp=lbp if side=='U' else [1.0-x for x in lap]
                        ls=lbs if side=='U' else las
                        ahead=mm._lvl(q,[x[j] for x in lp],[x[j] for x in ls])
    return fills

def run(coin,s,t,res,TL_HI=30.,TL_LO=2.,QMIN=0.96,IMP=1,SIZE=50.,LAT=0.2,SCAN=0.4,
        EVMAX=1.0,SIDE='both'):
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mm.bidx(s.ws.values); T=mm.bidx(t.ws.values)
    cols=dict(t=s.t.values,tl=s.tl.values,ub=s.ub.values,ua=s.ua.values,ubs=s.ubs.values,uas=s.uas.values)
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    EV=s.evage.values if 'evage' in s else np.zeros(len(s))
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        ta,tb=T.get(ws,(0,0))
        fl=bar_run(cols['tl'][a:b],cols['t'][a:b],cols['ub'][a:b],cols['ua'][a:b],
                   cols['ubs'][a:b],cols['uas'][a:b],
                   [x[a:b] for x in LBP],[x[a:b] for x in LBS],
                   [x[a:b] for x in LAP],[x[a:b] for x in LAS],EV[a:b],
                   Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb],win[ws],
                   TL_HI,TL_LO,QMIN,IMP,SIZE,LAT,SCAN,EVMAX,SIDE)
        for d in fl: d.update(coin=coin,ws=ws); out.append(d)
    return pd.DataFrame(out)

def score(d,lab,nbars):
    if not len(d): print(f'{lab:44s} NO FILLS'); return None
    d=d.copy(); d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    per=d.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'))
    sh=per.s.sum(); ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    day=d.assign(day=pd.to_datetime(d.ws,unit='s',utc=True).dt.date).groupby('day').pnl.sum()
    print(f'{lab:44s} bars={len(per):5d}/{nbars} sh={int(sh):7d} q={(d.q*d.f).sum()/sh:.4f} '
          f'wr={(d.win*d.f).sum()/sh:.5f} net={ps*100:+7.3f}+/-{se*100:5.3f} t={ps/se:+6.2f} '
          f'$/d={per.p.sum()/6:+8.1f} d+={int((day>0).sum())}/{len(day)}')
    return d
