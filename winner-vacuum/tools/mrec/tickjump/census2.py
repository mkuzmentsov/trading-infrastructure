"""Sell-pressure census BY PRICE BAND.  A resting BID at price p is hit by taker sell
pressure at <= p.  E[outcome - p] over that flow = the maker's gross edge before queue."""
import pandas as pd, numpy as np
PQ='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq'
t=pd.read_parquet(f'{PQ}/trades.parquet')
r=pd.read_parquet(f'{PQ}/res.parquet'); r['winT']=np.where(r.win=='UP','U','D')
t=t.merge(r[['coin','ws','winT']],on=['coin','ws'],how='inner')
t['tl']=t.ws+300-t.mts
t['day']=pd.to_datetime(t.ws,unit='s',utc=True).dt.date
opp={'U':'D','D':'U'}
s=t[t.side=='SELL'].copy(); b=t[t.side=='BUY'].copy()
b['tok']=b.tok.map(opp); b['px']=1-b.px
p=pd.concat([s,b],ignore_index=True)          # taker SELL of `tok` at `px`
p['isw']=(p.tok==p.winT)
p['pay']=p.isw.astype(float)
p['edge']=(p.pay-p.px)                        # per share, gross, no fee (maker)
p['reb']=0.2*0.07*p.px*(1-p.px)
BANDS=[(0.50,0.60),(0.60,0.70),(0.70,0.80),(0.80,0.90),(0.90,0.95),(0.95,0.98),(0.98,1.001)]
def rep(w,lab):
    print(f'\n########## {lab}   prints={len(w)} sh={int(w.sz.sum())}')
    rows=[]
    for lo,hi in BANDS:
        x=w[(w.px>=lo)&(w.px<hi)]
        if len(x)<50: continue
        sh=x.sz.sum(); notl=(x.px*x.sz).sum()
        g=(x.edge*x.sz).sum(); rb=(x.reb*x.sz).sum()
        # bar-clustered SE of per-share edge
        bc=x.groupby(['coin','ws']).apply(lambda d:pd.Series({'g':(d.edge*d.sz).sum()+ (d.reb*d.sz).sum(),'s':d.sz.sum()}),include_groups=False)
        pershare=(bc.g.sum()/bc.s.sum())
        se=np.sqrt(((bc.g-pershare*bc.s)**2).sum())/bc.s.sum()
        rows.append(dict(band=f'{lo:.2f}-{hi:.2f}',prints=len(x),sh=int(sh),notl=round(notl),
            wr=round(x.groupby(x.isw).sz.sum().get(True,0)/sh,4),
            c_sh_gross=round(g/sh*100,3), c_sh_net=round((g+rb)/sh*100,3),
            se=round(se*100,3), t=round(pershare/se,2) if se>0 else np.nan,
            usd_day=round((g+rb)/6,1), bars=bc.shape[0]))
    print(pd.DataFrame(rows).to_string(index=False))
rep(p[p.tl<30],'tl 0-30')
rep(p[(p.tl>=30)&(p.tl<60)],'tl 30-60')
rep(p[(p.tl>=60)&(p.tl<120)],'tl 60-120')
rep(p[(p.tl>=120)&(p.tl<=300)],'tl 120-300')
