import sys; sys.path.insert(0,'/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/winner-vacuum/tools/mrec')
"""polysim2 with the book-SHAPE panel (shape.parquet) so vetoes can see the ladders."""
import pandas as pd,numpy as np
pd.set_option('display.width',260)
FILLW=1.5; CLIP=8.0; LADDER=16.0; GAP=8.0
p=pd.read_parquet('shape.parquet')
t=__import__('lib').load_trades()
t=t[(t.side=='BUY')&(t.tl>=-2)&(t.tl<=60)]
tk={}
for (c,ws,tok),g in t.groupby(['coin','ws','tok']):
    tk[(c,ws,tok)]=(g.tl.values,g.px.values,g.sz.values)
KEEP=['coin','ws','day','tlk','fav_ask','fav_bid','fav_asz','est_bps','dB20','dB10','dB5','right','side',
      'adep','bdep','ashr','bshr','imb','imbs','spread','agap','bgap','gadep','gbdep',
      'dimb5','dimb10','dimb20','dbdep5','dbdep10','dbdep20','dadep20','vol','covg','hr']
def sim(tlo=3,thi=20,askmin=0.55,askmax=0.99,skip=(0.90,0.98),ladder_min=0.94,
        veto=None,thresh=0.10,slope=0.035,anchor=14.0,cov=0.5,coins=None,tape=True,fillw=FILLW,sweep=None):
    d=p[(p.tlk>=tlo)&(p.tlk<=thi)&(p.covg>=cov)&p.fav_ask.notna()&(p.fav_asz>0)].copy()
    if coins: d=d[d.coin.isin(coins)]
    d=d[d.est_bps.abs()>=(thresh+slope*np.maximum(0,d.tlk-anchor))]
    d=d[(d.fav_ask>=askmin)&(d.fav_ask<=askmax)]
    d=d.sort_values(['coin','ws','tlk'],ascending=[True,True,False])
    rows=[]
    for (c,ws),g in d.groupby(['coin','ws'],sort=False):
        spent=0.0; last=None; n=0
        for r in g.itertuples():
            if spent>=LADDER: break
            if last is not None and (last-r.tlk)<GAP: continue
            ask=r.fav_ask
            if n==0:
                if skip and skip[0]<=ask<=skip[1]: continue
            else:
                if ask<ladder_min: continue
            if veto is not None and veto(r): continue
            tok='U' if r.side=='UP' else 'D'
            e=tk.get((c,ws,tok)); fpx=ask; ok=True
            if tape:
                ok=False
                if e is not None:
                    tls,pxs,szs=e
                    m=(tls<=r.tlk)&(tls>r.tlk-fillw)&(pxs<=ask+1e-9)
                    if m.any():
                        ok=True; fpx=min(ask,float(pxs[m].max()))
                        if sweep is not None: fpx=max(fpx,ask-sweep)   # cap how far the FAK sweeps below the displayed ask
            if not ok: continue
            sh=min(CLIP,LADDER-spent)/fpx
            fee=0.07*fpx*(1-fpx)*sh
            pnl=(sh-fpx*sh-fee) if r.right else (-fpx*sh-fee)
            rows.append(tuple(getattr(r,k) for k in KEEP)+(ask,fpx,sh,fpx*sh,pnl,r.right,n))
            spent+=fpx*sh; last=r.tlk; n+=1
    return pd.DataFrame(rows,columns=KEEP+['ask','fpx','sh','cost','pnl','won','clip'])
def rep(f,label):
    nd=f.day.nunique(); dy=f.groupby('day').pnl.sum()
    print(f'{label:34s} clips={len(f):4d} stake=${f.cost.sum():6.0f} pnl=${f.pnl.sum():8.2f} roi={f.pnl.sum()/max(f.cost.sum(),1)*100:6.2f}% '
          f'win={f.won.mean():.3f} ${f.pnl.sum()/nd:7.2f}/day  worstday=${dy.min():7.2f} posdays={int((dy>0).sum())}/{len(dy)} '
          f'loss/day={(f.pnl<-0.5).sum()/nd:.1f}')
    return dy
def vetbid(r,th=-0.03,estmax=5.0):
    db=r.dB20
    if db!=db: return False
    return (abs(r.est_bps)<estmax) and (db<=th)
