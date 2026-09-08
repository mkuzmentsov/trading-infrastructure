"""Two-sided resting-maker simulator on the mrec v2 REAL PRINT TAPE (bug #11 queue,
bug #28 tape-size cap).  Emits ONE ROW PER (epoch, side) in LONG form: every resting
quote is a BID in its own token's space (a U ask at A == a D bid at 1-A, the book is
one book: ua == 1-db in 99.999% of snaps).

Fill model for a bid at q held over window W:
    V   = shares of taker sell-pressure printed at price <= q inside W  (own token space)
    fill= min(SIZE, max(0, V - ahead)),  ahead = displayed size at q at placement (0 if NOQ
          or if we improve to a new level).  Fill price = q (maker fills at own price).
Fill instant = first print at which the running (V - ahead) turns positive.
"""
import sys, os
import pandas as pd, numpy as np

PQ='pq'
COINS=['btc','eth','sol','xrp','bnb','doge','hype']
TICK=0.01

def load_coin(coin):
    s=pd.read_parquet(f'{PQ}/snapcur.parquet',
        columns=['coin','ws','t','tl','ub','ubs','ua','uas','vol','volsh','spot','lead_bps',
                 'evage','ubd0p','ubd0s','ubd1p','ubd1s','ubd2p','ubd2s',
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

def _lvl(P,lp,ls):
    for p,z in zip(lp,ls):
        if p==p and abs(p-P)<1e-6: return z if z==z else 0.0
    return 0.0

def run(coin, DELTA=0, SIZE=50.0, H=10.0, STEP=10.0, TL_HI=270.0, TL_LO=40.0,
        QLO=0.04, QHI=0.60, MAXFILL=999, cancel_other=False, LAT=0.2, LATP=0.2,
        noq=False, s=None,t=None,res=None, seed=0):
    """DELTA: +1 = improve one tick inside; 0 = join touch; -1/-2 = rest behind."""
    if s is None: s,t,res=load_coin(coin)
    win={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=bidx(s.ws.values); T=bidx(t.ws.values)
    St,Stl,Sub,Sua,Subs,Suas,Svol,Svsh=[s[c].values for c in ('t','tl','ub','ua','ubs','uas','vol','volsh')]
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    out=[]
    for ws,(a,b) in S.items():
        if ws not in win: continue
        wU=win[ws]
        ta,tb=T.get(ws,(0,0))
        tt,tp,tsz,tsl=Tt[ta:tb],Tp[ta:tb],Tsz[ta:tb],Tsl[ta:tb]
        st,stl=St[a:b],Stl[a:b]
        nf={'U':0,'D':0}
        tl=TL_HI
        while tl>=TL_LO:
            j=np.searchsorted(-stl,-tl)
            if j>=len(stl): break
            if abs(stl[j]-tl)>1.5: tl-=STEP; continue
            k=a+j; ub,ua=Sub[k],Sua[k]
            if not(ub==ub and ua==ua and ua>ub): tl-=STEP; continue
            t0=st[j]; tw0=t0+LATP; tw1=t0+H
            i0=np.searchsorted(tt,tw0,'right'); i1=np.searchsorted(tt,tw1,'right')
            wtt,wtp,wsz,wsl=tt[i0:i1],tp[i0:i1],tsz[i0:i1],tsl[i0:i1]
            ev={}
            for side in ('U','D'):
                if nf[side]>=MAXFILL: continue
                if side=='U':
                    q=round(ub+DELTA*TICK,3); opp=ua; mq=(ub+ua)/2
                    lp=[LBP[i][k] for i in range(3)]; ls=[LBS[i][k] for i in range(3)]
                    ourdepth,oppdepth=Subs[k],Suas[k]
                else:
                    q=round(1.0-ua+DELTA*TICK,3); opp=1.0-ub; mq=1-(ub+ua)/2
                    lp=[1.0-LAP[i][k] for i in range(3)]; ls=[LAS[i][k] for i in range(3)]
                    ourdepth,oppdepth=Suas[k],Subs[k]
                if not(QLO<=q<=QHI) or q>=opp: continue
                ahead=0.0 if (noq or DELTA>0) else _lvl(q,lp,ls)
                if side=='U': m=wsl&(wtp<=q+1e-9)
                else:         m=(~wsl)&(wtp>=1.0-q-1e-9)
                f=0.0; tf=np.nan
                if m.any():
                    cs=np.cumsum(wsz[m])-ahead
                    if cs[-1]>0:
                        f=min(SIZE,cs[-1]); tf=wtt[m][int(np.argmax(cs>0))]
                ev[side]=dict(q=q,opp=opp,mq=mq,ahead=ahead,f=f,tf=tf,
                              ourdepth=ourdepth,oppdepth=oppdepth,tape=wsz[m].sum() if m.any() else 0.0)
            if cancel_other and len(ev)==2:
                fu,fd=ev['U'],ev['D']
                if fu['f']>0 and fd['f']>0:
                    if fu['tf']<fd['tf'] and fd['tf']>fu['tf']+LAT: fd['f']=0.0; fd['tf']=np.nan
                    elif fd['tf']<fu['tf'] and fu['tf']>fd['tf']+LAT: fu['f']=0.0; fu['tf']=np.nan
            for side,e in ev.items():
                midf=np.nan
                if e['f']>0:
                    nf[side]+=1
                    jj=np.searchsorted(st,e['tf'],'right')-1
                    if jj>=0:
                        m2=(Sub[a+jj]+Sua[a+jj])/2
                        midf=m2 if side=='U' else 1-m2
                out.append(dict(coin=coin,ws=ws,tl=tl,side=side,q=e['q'],mq=e['mq'],
                    spr=round(e['opp']-e['q'] if DELTA==0 else Sua[k]-Sub[k],3),
                    ahead=e['ahead'],f=e['f'],tf=e['tf'],midf=midf,tape=e['tape'],
                    ourdepth=e['ourdepth'],oppdepth=e['oppdepth'],vol=Svol[k],volsh=Svsh[k],
                    win=(wU if side=='U' else 1-wU)))
            tl-=STEP
    d=pd.DataFrame(out)
    if len(d):
        d['hr']=pd.to_datetime(d.ws,unit='s',utc=True).dt.hour
        d['day']=pd.to_datetime(d.ws,unit='s',utc=True).dt.date.astype(str)
    return d

def runall(**kw):
    A=[]
    for c in COINS:
        try: s,t,r=load_coin(c)
        except Exception as e: print('skip',c,e); continue
        if len(s)==0: continue
        A.append(run(c,s=s,t=t,res=r,**kw))
    return pd.concat(A,ignore_index=True)

if __name__=='__main__':
    import time; t0=time.time()
    tag=sys.argv[1] if len(sys.argv)>1 else 'base'
    kw=dict(DELTA=int(os.environ.get('DELTA',0)),noq=os.environ.get('NOQ','0')=='1',
            cancel_other=os.environ.get('CANC','0')=='1',SIZE=float(os.environ.get('SIZE',50)))
    d=runall(**kw); d.to_parquet(f'ep_{tag}.parquet',index=False)
    print(tag,kw,len(d),'quotes  fills',(d.f>0).sum(),'%.0fs'%(time.time()-t0))
