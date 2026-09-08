"""EXIT LANE simulator.  Takes a clip set from polysim2.sim(), walks each clip forward
second-by-second through the panel, and applies a CAUSAL stop rule.
Fill models for the exit sell:
  disp   : fill at the displayed bid on our token at the trigger second
  lag1   : decide at k, fill at the displayed bid one second later (k-1)   [latency stress]
  tick   : fill 1c below the displayed bid
  tape   : require a real SELL print on our token in (k-1.5,k] at px>=b-0.02; fill=min(b,max print)
Fee both legs: 0.07*p*(1-p) per share.
"""
import pandas as pd, numpy as np, sys, itertools
pd.set_option('display.width',260)
KMIN=3   # never exit inside the last 3s (TWAP already closed at T-3)

P=pd.read_parquet('pq/panelflow3.parquet',
    columns=['coin','ws','tlk','ub','ubs','db','dbs','est_bps','covg','side'])
ARR={}
for (co,ws),g in P.sort_values(['coin','ws','tlk']).groupby(['coin','ws'],sort=False):
    k=g.tlk.values.astype(int); n=91
    a=[np.full(n,np.nan) for _ in range(5)]
    a[0][k]=g.ub.values; a[1][k]=g.db.values
    a[2][k]=g.ubs.values; a[3][k]=g.dbs.values
    a[4][k]=g.est_bps.values
    ARR[(co,ws)]=a
SIDE=P.set_index(['coin','ws','tlk'])['side']

T=pd.read_parquet('pq/trades.parquet',columns=['coin','ws','tok','px','sz','side','mts'])
T=T[T.side=='SELL'].copy(); T['tl']=T.ws+300-T.mts
T=T[(T.tl>=0)&(T.tl<=70)]
SEL={}
for (co,ws,tok),g in T.groupby(['coin','ws','tok']):
    SEL[(co,ws,tok)]=(g.tl.values,g.px.values)

def prep(path):
    c=pd.read_parquet(path)
    c['tok']=np.where(SIDE.loc[list(zip(c.coin,c.ws,c.tl))].values=='UP','U','D')
    ent=[]
    for r in c.itertuples():
        a=ARR[(r.coin,r.ws)]
        ent.append(a[0][r.tl] if r.tok=='U' else a[1][r.tl])
    c['b_ent']=ent
    c['efee']=0.07*c.fpx*(1-c.fpx)*c.sh
    return c

def run(c,trig,fill='disp',kmin=KMIN,dwell=1):
    out=[]
    for r in c.itertuples():
        a=ARR[(r.coin,r.ws)]
        bid = a[0] if r.tok=='U' else a[1]
        bsz = a[2] if r.tok=='U' else a[3]
        est = a[4] if r.tok=='U' else -a[4]
        e=SEL.get((r.coin,r.ws,r.tok))
        exited=False; q=np.nan; kx=np.nan
        for k in range(r.tl-dwell, kmin-1, -1):
            b=bid[k]
            if b!=b: continue
            if not trig(r,k,b,bsz[k],est[k],bid,est): continue
            if fill=='disp': q=b
            elif fill=='tick': q=max(b-0.01,0.0)
            elif fill=='lag1':
                q=bid[k-1] if k-1>=0 and bid[k-1]==bid[k-1] else b
            elif fill=='tape':
                if e is None: continue
                tls,pxs=e
                m=(tls<=k)&(tls>k-1.5)&(pxs>=b-0.02)
                if not m.any(): continue
                q=min(b,float(pxs[m].max()))
            exited=True; kx=k; break
        if exited:
            xfee=0.07*q*(1-q)*r.sh
            pnl=r.sh*(q-r.fpx)-r.efee-xfee
        else:
            pnl=r.pnl
        out.append((pnl,exited,q,kx))
    o=pd.DataFrame(out,columns=['xpnl','exited','xq','xk'],index=c.index)
    return pd.concat([c,o],axis=1)

def rep(f,label):
    nd=f.day.nunique()
    ex=f[f.exited]
    exw=int((ex.won).sum()); exl=int((~ex.won).sum())
    base=f.pnl.sum(); new=f.xpnl.sum()
    dayb=f.groupby('day').pnl.sum(); dayn=f.groupby('day').xpnl.sum()
    print(f'{label:38s} exits={len(ex):4d} (W {exw:3d} / L {exl:3d})  pnl ${base:8.2f} -> ${new:8.2f} '
          f'({(new-base)/nd:+6.2f}/day)  worstday ${dayb.min():7.2f}->${dayn.min():7.2f}  '
          f'worstbar ${f.pnl.min():6.2f}->${f.xpnl.min():6.2f}  losers/day {(f.pnl<-0.5).sum()/nd:.1f}->{(f.xpnl<-0.5).sum()/nd:.1f}')
    return dayn
