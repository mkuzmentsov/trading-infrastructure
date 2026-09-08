"""MID-BAND MAKER COST HARNESS (agent C).  Event-driven, one resting order per side per bar
(re-placed per policy), REAL print tape, queue-ahead at placement (bug #11), tape-size capped
(bug #28), evage<1s (bug #34), TERMINAL PnL win-q + rebate (bug #37) with the 3-term
decomposition, AND resting share-seconds inside the reward band (what a rewards program pays).

PLACE : join    q = touch bid
        behind  q = touch - 1 tick
        improve q = touch + 1 tick, only when spread >= 2 ticks (else no quote)
        edge05  q = highest tick <= mid - 0.005   (rewfarm's chosen 0.5c-inside band edge)
        edge15  q = highest tick <= mid - 0.015   (far edge of the Aug 1.5c reward band)
MODE  : static  hold the order H seconds (or until fill), then re-place at the target
        cancel  re-place whenever the target price changes (cancel-on-touch-move)
SIDES : both | U | D | rand   (rand = one side per bar, seeded: the placebo)
MAXFILL fills of SIZE per side per bar; hold to settlement.
Share-seconds: accumulated while resting, in-band = |q - mid_now| <= BAND and SIZE >= 50.
"""
import pandas as pd, numpy as np, sys, os
from multiprocessing import Pool
PQ='pq'; COINS=['btc','eth','sol','xrp','bnb','doge','hype']
TICK=0.01

def load_coin(coin):
    s=pd.read_parquet(f'{PQ}/snapcur.parquet',
        columns=['coin','ws','t','tl','ub','ubs','ua','uas','evage',
                 'ubd0p','ubd0s','ubd1p','ubd1s','ubd2p','ubd2s',
                 'uad0p','uad0s','uad1p','uad1s','uad2p','uad2s'],
        filters=[('coin','==',coin)]).sort_values(['ws','t']).reset_index(drop=True)
    t=pd.read_parquet(f'{PQ}/trades.parquet',filters=[('coin','==',coin)])
    pU=np.where(t.tok.values=='U', t.px.values, 1.0-t.px.values)
    sell=((t.tok.values=='U')&(t.side.values=='SELL'))|((t.tok.values=='D')&(t.side.values=='BUY'))
    t=t.assign(pU=np.round(pU,3),sellp=sell).sort_values(['ws','t']).reset_index(drop=True)
    res=pd.read_parquet(f'{PQ}/res.parquet'); res=res[res.coin==coin][['ws','win']]
    return s,t,res

def bidx(a):
    u,st=np.unique(a,return_index=True); return dict(zip(u,zip(st,np.append(st[1:],len(a)))))

def tfloor(x): return np.floor(x/TICK+1e-9)*TICK

def bar_sim(side,st,stl,bb,ba,lp,ls,evg,tt,tp,tsz,tsl,win,P):
    """side-agnostic: bb/ba/lp/ls already in the quoted token's space; prints: sellp==True and
    tp<=q hit us (U-space) — caller mirrors for D."""
    PLACE,MODE,SIZE,MAXFILL,H,LAT,SCAN,TL_HI,TL_LO,QLO,QHI,BAND=(P[k] for k in
        ('PLACE','MODE','SIZE','MAXFILL','H','LAT','SCAN','TL_HI','TL_LO','QLO','QHI','BAND'))
    fills=[]; ss_band=0.0; ss_all=0.0; nplace=0
    q=None; live=np.inf; placed=-1e18; rem=SIZE; ahead=0.0; nf=0; mq=np.nan
    last=-1e18; ip=0; prev_t=None
    for j in range(len(st)):
        tl=stl[j]
        if tl>TL_HI: continue
        if tl<TL_LO: break
        if st[j]-last<SCAN: continue
        t_now=st[j]; dt=(t_now-prev_t) if prev_t is not None else 0.0; prev_t=t_now; last=t_now
        b,a=bb[j],ba[j]
        fresh = not(evg[j]==evg[j] and evg[j]>1.0)
        # ---- process prints since last scan against the current order
        while ip<len(tt) and tt[ip]<=t_now:
            if q is not None and rem>0 and tt[ip]>=live and tsl[ip] and tp[ip]<=q+1e-9:
                take=tsz[ip]-ahead
                if take>0:
                    ahead=0.0; f=min(rem,take); rem-=f
                    fills.append(dict(q=q,f=f,mq=mq,tf=tt[ip],tl=tl,win=win,ahead0=ahead0))
                    if rem<=1e-9:
                        nf+=1; q=None; live=np.inf
                        if nf<MAXFILL: rem=SIZE
                else: ahead-=tsz[ip]
            ip+=1
        # ---- share-seconds while resting (before any re-placement this scan)
        if q is not None and t_now>=live and b==b and a==a:
            mid=(b+a)/2; ss_all+=rem*dt
            # rewards config attaches ~50s after open (Aug mechanics) -> only tl<=SS_TL_HI scores
            if SIZE>=50 and abs(q-mid)<=BAND+1e-9 and tl<=P.get('SS_TL_HI',250.): ss_band+=rem*dt
        if nf>=MAXFILL: continue
        # ---- target
        tgt=None
        if fresh and b==b and a==a and a>b:
            mid=(b+a)/2
            if PLACE=='join': tgt=round(b,3)
            elif PLACE=='behind': tgt=round(b-TICK,3)
            elif PLACE=='improve': tgt=round(b+TICK,3) if (a-b)>=2*TICK-1e-9 else None
            elif PLACE=='improve3': tgt=round(b+TICK,3) if (a-b)>=3*TICK-1e-9 else None
            elif PLACE=='edge05': tgt=round(tfloor(mid-0.005),3)
            elif PLACE=='edge15': tgt=round(tfloor(mid-0.015),3)
            if tgt is not None and (tgt<QLO or tgt>QHI or tgt>=a): tgt=None
        # ---- placement policy
        replace=False
        if q is None:
            replace = tgt is not None
        else:
            if MODE=='cancel': replace = (tgt!=q)
            else: replace = (t_now-placed>=H) and (tgt!=q)
            if tgt is None and MODE=='cancel': q=None; live=np.inf
        if replace:
            if tgt is None: q=None; live=np.inf; continue
            q=tgt; placed=t_now; live=t_now+LAT; mq=(b+a)/2; nplace+=1
            ahead=0.0
            if not PLACE.startswith('improve'):
                for p_,z_ in zip((x[j] for x in lp),(x[j] for x in ls)):
                    if p_==p_ and abs(p_-q)<1e-6: ahead=(z_ if z_==z_ else 0.0); break
            ahead0=ahead
    return fills,ss_band,ss_all,nplace

def run_coin(args):
    coin,P=args
    s,t,res=load_coin(coin)
    winmap={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=bidx(s.ws.values); T=bidx(t.ws.values)
    st,stl,ub,ua,ev=s.t.values,s.tl.values,s.ub.values,s.ua.values,s.evage.values
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    rng=np.random.default_rng(hash(coin)%2**32)
    F=[]; B=[]
    for ws,(a,b) in S.items():
        if ws not in winmap: continue
        wU=winmap[ws]; ta,tb=T.get(ws,(0,0))
        sides=('U','D') if P['SIDES']=='both' else ((P['SIDES'],) if P['SIDES'] in ('U','D') else (rng.choice(['U','D']),))
        # mid-at-fill lookup helper
        sst=st[a:b]; smid=(ub[a:b]+ua[a:b])/2
        for side in sides:
            if side=='U':
                bb,ba=ub[a:b],ua[a:b]; lp=[x[a:b] for x in LBP]; ls=[x[a:b] for x in LBS]
                tp=Tp[ta:tb]; tsl=Tsl[ta:tb]; win=wU
            else:
                bb,ba=1.0-ua[a:b],1.0-ub[a:b]; lp=[1.0-x[a:b] for x in LAP]; ls=[x[a:b] for x in LAS]
                tp=1.0-Tp[ta:tb]; tsl=~Tsl[ta:tb]; win=1-wU
            fl,ssb,ssa,npl=bar_sim(side,sst,stl[a:b],bb,ba,lp,ls,ev[a:b],Tt[ta:tb],tp,Tsz[ta:tb],tsl,win,P)
            for d in fl:
                jj=np.searchsorted(sst,d['tf'],'right')-1
                m2=smid[max(jj,0)]; d['midf']=m2 if side=='U' else 1-m2
                d.update(coin=coin,ws=ws,side=side); F.append(d)
            B.append(dict(coin=coin,ws=ws,side=side,ss_band=ssb,ss_all=ssa,nplace=npl,nfill=len(fl)))
    return pd.DataFrame(F),pd.DataFrame(B)

DEF=dict(PLACE='join',MODE='static',SIZE=50.,MAXFILL=1,H=10.,LAT=0.2,SCAN=0.5,
         TL_HI=250.,TL_LO=40.,QLO=0.20,QHI=0.80,BAND=0.015,SIDES='both')

def run(P,coins=COINS,procs=7):
    P={**DEF,**P}
    with Pool(procs) as pool:
        R=pool.map(run_coin,[(c,P) for c in coins])
    F=pd.concat([r[0] for r in R],ignore_index=True); B=pd.concat([r[1] for r in R],ignore_index=True)
    return F,B

def score(F,B,lab,days=6.0):
    if len(F): 
        F=F.copy(); F['reb']=0.2*0.07*F.q*(1-F.q); F['pnl']=F.f*((F.win-F.q)+F.reb)
        sh=F.f.sum(); w=lambda x:(x*F.f).sum()/sh
        per=F.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'))
        ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
        hs,dr,ad=w(F.mq-F.q)*100,w(F.midf-F.mq)*100,w(F.win-F.midf)*100
        loss=int((F.win==0).sum()); usd=per.p.sum()/days
        # pairs: both sides filled in the same bar
        pr=F.groupby(['coin','ws']).side.nunique(); pair=(pr==2).mean()
    else:
        sh=0; ps=se=hs=dr=ad=usd=0; loss=0; pair=0; per=pd.DataFrame()
    ssb=B.ss_band.sum()/days; ssa=B.ss_all.sum()/days
    r=dict(lab=lab,fills=len(F),sh_day=round(sh/days),net_usd_day=round(usd,1),
           c_sh=round(ps*100,3),se=round(se*100,3),hs=round(hs,3),drift=round(dr,3),adv=round(ad,3),
           loss_ev=loss,pair=round(pair,3),ss_band_kday=round(ssb/1000,1),ss_all_kday=round(ssa/1000,1),
           usd_per_kss=round(usd/(ssb/1000),3) if ssb>0 else np.nan)
    return r,F,B

if __name__=='__main__':
    import time; t0=time.time()
    r,F,B=score(*run({}),'join static 50 both')
    print(r,'%.0fs'%(time.time()-t0))
