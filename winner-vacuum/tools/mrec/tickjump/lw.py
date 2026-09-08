"""LATE-WINDOW maker, high-price band.  mm.py drops every epoch where the favourite has
no ask (83% of late seconds), so the 0.96-0.999 cell was never sampled.  Here a BID needs
only a bid to join, and above 0.96 the tick is 0.001 so a one-tick improvement jumps the
whole displayed queue for 0.1c.
Fill = taker sell pressure at <= q in the token's own space, after clearing `ahead`.
"""
import mm, pandas as pd, numpy as np, sys, time
def run(coin,s,t,res,TL_HI=60.,TL_LO=2.,STEP=2.,H=6.,LAT=0.2,IMP=0,SIZE=50.,QMIN=0.90):
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mm.bidx(s.ws.values); T=mm.bidx(t.ws.values)
    St,Stl,Sub,Sua,Subs,Suas=[s[c].values for c in ('t','tl','ub','ua','ubs','uas')]
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]; ta,tb=T.get(ws,(0,0))
        tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        st,stl=St[a:b],Stl[a:b]; tl=TL_HI
        while tl>=TL_LO:
            j=np.searchsorted(-stl,-tl)
            if j>=len(stl): break
            if abs(stl[j]-tl)>1.0: tl-=STEP; continue
            k=a+j; ub,ua=Sub[k],Sua[k]
            t0=st[j]; i0=np.searchsorted(tt,t0+LAT,'right'); i1=np.searchsorted(tt,t0+H,'right')
            wtp,wsz,wsl=tp[i0:i1],tsz[i0:i1],tsl[i0:i1]
            for side in ('U','D'):
                base = ub if side=='U' else (1.0-ua if ua==ua else np.nan)
                if not(base==base) or base<QMIN or base>=0.999: continue
                tick=0.001 if base>=0.96 else 0.01
                q=round(base+IMP*tick,3)
                if q>=0.9995: continue
                # do not cross the opposite side
                opp = ua if side=='U' else (1.0-ub if ub==ub else 1.0)
                if opp==opp and q>=opp: continue
                if side=='U':
                    lp=[LBP[i][k] for i in range(3)]; ls=[LBS[i][k] for i in range(3)]
                else:
                    lp=[1.0-LAP[i][k] for i in range(3)]; ls=[LAS[i][k] for i in range(3)]
                ahead=0.0 if IMP>0 else mm._lvl(q,lp,ls)
                m=(wsl&(wtp<=q+1e-9)) if side=='U' else ((~wsl)&(wtp>=1.0-q-1e-9))
                f=0.0
                if m.any():
                    cs=np.cumsum(wsz[m])-ahead
                    if cs[-1]>0: f=min(SIZE,cs[-1])
                out.append(dict(coin=coin,ws=ws,tl=tl,side=side,q=q,ahead=ahead,f=f,
                                tape=wsz[m].sum() if m.any() else 0.0,
                                win=(wU if side=='U' else 1-wU)))
            tl-=STEP
    return pd.DataFrame(out)

def score(d,lab):
    d=d.copy(); d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    f=d[d.f>0]
    if not len(f): print(lab,'no fills'); return
    per=f.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'))
    sh=per.s.sum(); ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    days=f.assign(day=pd.to_datetime(f.ws,unit='s',utc=True).dt.date).groupby('day').apply(
        lambda g:(g.f*((g.win-g.q)+0.2*0.07*g.q*(1-g.q))).sum(),include_groups=False)
    print(f'{lab:34s} ord={len(d):6d} fills={len(f):5d} ({len(f)/len(d)*100:4.1f}%) sh={int(sh):7d} '
          f'q={(f.q*f.f).sum()/sh:.4f} wr={(f.win*f.f).sum()/sh:.4f} '
          f'net={ps*100:+7.3f} +/-{se*100:5.3f} t={ps/se:+6.2f} $/d={per.p.sum()/6:+8.1f} '
          f'days+={int((days>0).sum())}/{len(days)}')

if __name__=='__main__':
    D={}
    for c in mm.COINS:
        s,t,r=mm.load_coin(c); D[c]=(s,t,r)
    for QMIN,TLH in [(0.90,60.),(0.90,30.),(0.96,60.),(0.96,30.),(0.80,60.)]:
        for IMP in (0,1,2):
            A=[run(c,*D[c],TL_HI=TLH,QMIN=QMIN,IMP=IMP) for c in mm.COINS]
            score(pd.concat(A,ignore_index=True),f'QMIN{QMIN} tl<={int(TLH)} IMP+{IMP}tick')
        print()
