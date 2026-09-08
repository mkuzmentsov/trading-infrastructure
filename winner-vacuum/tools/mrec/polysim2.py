"""Vacmaker policy replay on mrec v2, with TAPE-CONFIRMED fills.
A fire at (coin,ws,tl,ask) counts only if a real BUY print exists on the same
token at px<=ask within [t, t+FILLW]; fill px = min(displayed ask, print px)."""
import pandas as pd,numpy as np
pd.set_option('display.width',250)
FILLW=1.5
CLIP=8.0; LADDER=16.0; GAP=8.0
p=pd.read_parquet('pq/panelflow3.parquet')
t=__import__('lib').load_trades()
t=t[(t.side=='BUY')&(t.tl>=-2)&(t.tl<=60)]
tk={}
for (c,ws,tok),g in t.groupby(['coin','ws','tok']):
    tk[(c,ws,tok)]=(g.tl.values, g.px.values, g.sz.values)

def sim(tlo=3,thi=20,askmin=0.55,askmax=0.99,skip=(0.90,0.98),ladder_min=0.94,
        veto=None, thresh=0.10, slope=0.035, anchor=14.0, cov=0.5, coins=None, tape=True):
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
            e=tk.get((c,ws,tok))
            fpx=ask; ok=True
            if tape:
                ok=False
                if e is not None:
                    tls,pxs,szs=e
                    m=(tls<=r.tlk)&(tls>r.tlk-FILLW)&(pxs<=ask+1e-9)
                    if m.any(): ok=True; fpx=min(ask,float(pxs[m].max()))
            if not ok: continue
            sh=min(CLIP,LADDER-spent)/fpx
            fee=0.07*fpx*(1-fpx)*sh
            pnl=(sh-fpx*sh-fee) if r.right else (-fpx*sh-fee)
            rows.append((c,ws,r.day,r.tlk,ask,fpx,sh,fpx*sh,pnl,r.right,n,r.dirflow30,r.est_bps,r.dB20,r.dB10))
            spent+=fpx*sh; last=r.tlk; n+=1
    f=pd.DataFrame(rows,columns=['coin','ws','day','tl','ask','fpx','sh','cost','pnl','won','clip','df30','est','dB20','dB10'])
    return f
def rep(f,label):
    nd=f.day.nunique(); nb=f.groupby(['coin','ws']).ngroups
    print(f'{label}: clips={len(f)} bars={nb} stake=${f.cost.sum():.0f} '
          f'pnl=${f.pnl.sum():.2f} roi={f.pnl.sum()/f.cost.sum()*100:.2f}% win={f.won.mean():.3f} ${f.pnl.sum()/nd:.2f}/day')

def vet(r,th=-0.03,estmax=5.0,L=20):
    db=getattr(r,f'dB{L}')
    if db!=db: return False
    return (abs(r.est_bps)<estmax) and (db<=th)
if __name__=='__main__':
    base=sim(); rep(base,'BASELINE            '); base.to_parquet('pq/sim_base3.parquet',index=False)
    for th in (-0.02,-0.03,-0.05,-0.10):
        v=sim(veto=lambda r,th=th: vet(r,th)); rep(v,f'+ BIDDROP VETO dB20<={th}')
    v=sim(veto=lambda r: vet(r,-0.03,L=10)); rep(v,'+ BIDDROP VETO dB10<=-0.03')
    v=sim(veto=lambda r: vet(r,-0.03,estmax=1e9)); rep(v,'+ BIDDROP VETO dB20<=-0.03 (no est exemption)')
    best=sim(veto=lambda r: vet(r,-0.03)); best.to_parquet('pq/sim_veto.parquet',index=False)
    print()
    for lab,f in (('base',base),('veto',best)):
        g=f.groupby('day').pnl.sum().round(2); print(lab, dict(g))
