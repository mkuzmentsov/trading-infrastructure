"""LATE-WINDOW RESTING BID on the favourite.  Place a post-only bid at q on the
estimated-winner token at tl=T0, leave it to the close, fill from the REAL print tape.

Fill models
  STRICT  : only taker sell pressure printed STRICTLY BELOW q fills us (the book was
            walked through our level, so our order must have been consumed first).
  LOOSE   : pressure at <= q fills us (zero queue at our own level) -- upper bound.
Size cap  : the pressure volume itself (bug #28), and the clip.
PnL       : sh*(outcome - q) + rebate 0.2*0.07*q*(1-q).  Maker pays no fee.
"""
import pandas as pd, numpy as np, sys
PQ='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq'

def load():
    t=pd.read_parquet(f'{PQ}/trades.parquet')
    r=pd.read_parquet(f'{PQ}/res.parquet'); r['winT']=np.where(r.win=='UP','U','D')
    t=t.merge(r[['coin','ws','winT']],on=['coin','ws'],how='inner')
    t['tl']=t.ws+300-t.mts
    opp={'U':'D','D':'U'}
    s=t[t.side=='SELL'][['coin','ws','tok','px','sz','tl']].copy()
    b=t[t.side=='BUY' ][['coin','ws','tok','px','sz','tl']].copy()
    b['tok']=b.tok.map(opp); b['px']=1-b.px
    p=pd.concat([s,b],ignore_index=True)
    p=p[(p.tl>0)&(p.tl<=90)]
    pan=pd.read_parquet(f'{PQ}/panel.parquet',
        columns=['coin','ws','tlk','evage','est_bps','cov','obs','side','win','ub','db','ubs','dbs'])
    return p,pan,r

def sim(p,pan,r,T0=30,mode='est',estmin=0.5,covmin=0.5,clip=24.0,dmin=0.0):
    d=pan[pan.tlk==T0].copy()
    d=d[(d.evage<1.0)]
    d['favT']=np.where(d.ub>=d.db,'U','D')                       # market favourite by bid
    d['estT']=np.where(d.side=='UP','U','D')
    d['favbid']=np.where(d.favT=='U',d.ub,d.db)
    if mode=='est':
        d=d[(d.est_bps.abs()>=estmin)&(d["cov"]>=covmin)]
        d['tok']=d.estT; d['q0']=np.where(d.tok=='U',d.ub,d.db)
    elif mode=='fav':
        d['tok']=d.favT; d['q0']=d.favbid
    elif mode=='dog':                                            # control: quote the underdog
        d['tok']=np.where(d.favT=='U','D','U'); d['q0']=np.where(d.tok=='U',d.ub,d.db)
    d=d[d.q0.notna()&(d.q0>0.02)]
    d=d.merge(r[['coin','ws','winT']],on=['coin','ws'],how='inner')
    d['isw']=(d.tok==d.winT)
    # pressure in the quoted token's space, inside (0, T0]
    w=p[p.tl<=T0]
    m=w.merge(d[['coin','ws','tok','q0','isw']],on=['coin','ws','tok'],how='inner')
    out=[]
    for lab,dlt in [('-1c',0.01),('-2c',0.02),('-3c',0.03),('-5c',0.05),('-10c',0.10),
                    ('-15c',0.15),('-20c',0.20),('-30c',0.30)]:
        dd=d.copy(); dd['q']=(dd.q0-dlt).round(3)
        dd=dd[dd.q>=dmin]
        mm=m.merge(dd[['coin','ws','q']],on=['coin','ws'],how='inner')
        for fm,cond in [('STRICT',mm.px<mm.q-1e-9),('LOOSE',mm.px<=mm.q+1e-9)]:
            f=mm[cond].groupby(['coin','ws']).agg(vol=('sz','sum')).reset_index()
            x=dd.merge(f,on=['coin','ws'],how='left'); x['vol']=x.vol.fillna(0.0)
            x['sh']=np.minimum(clip/x.q,x.vol)
            fl=x[x.sh>0]
            if len(fl)<5: continue
            sh=fl.sh.sum(); cost=(fl.sh*fl.q).sum()
            gross=(fl.sh*(fl.isw.astype(float)-fl.q)).sum()
            reb=(fl.sh*0.2*0.07*fl.q*(1-fl.q)).sum()
            net=gross+reb
            per=fl.groupby(['coin','ws']).apply(lambda z:pd.Series(
                {'n':(z.sh*(z.isw.astype(float)-z.q)).sum()+(z.sh*0.2*0.07*z.q*(1-z.q)).sum(),
                 's':z.sh.sum()}),include_groups=False)
            ps=per.n.sum()/per.s.sum(); se=np.sqrt(((per.n-ps*per.s)**2).sum())/per.s.sum()
            out.append(dict(lvl=lab,fill=fm,orders=len(x),filled=len(fl),
                fillpct=round(len(fl)/len(x)*100,1),sh=round(sh),meanq=round(fl.q.mean(),3),
                wr=round((fl.sh*fl.isw).sum()/sh,4),cost=round(cost),
                c_sh=round(net/sh*100,3),se=round(se*100,3),t=round(ps/se,2) if se>0 else np.nan,
                usd_day=round(net/6,2)))
    return pd.DataFrame(out)

if __name__=='__main__':
    p,pan,r=load()
    for T0 in (30,45,60,90):
        for mode in ('est','fav'):
            print(f'\n##### T0={T0}s  side={mode}  clip=$24')
            print(sim(p,pan,r,T0=T0,mode=mode).to_string(index=False))
