"""Lead 4a: extend the live fire window below tl=3 (down to T+0 / T-2).  polysim2 logic with the
HOUSE fill model (bug #27): FILLW 0.4s, fill AT the displayed ask (no improvement), CLIP 24 / LADDER 48,
tape-confirmed.  Live gate otherwise (thresh 0.10 + 0.035*(tl-14) slope, cov 0.5, skip 0.90-0.98)."""
import pandas as pd,numpy as np,sys
sys.path.insert(0,'.')
import lib
FILLW=0.4; CLIP=24.0; LADDER=48.0; GAP=8.0
p=pd.read_parquet('pq/panel.parquet')
print('panel tlk range',p.tlk.min(),p.tlk.max(),'rows',len(p))
t=lib.load_trades(); t=t[(t.side=='BUY')&(t.tl>=-5)&(t.tl<=60)]
tk={k:(g.tl.values,g.px.values,g.sz.values) for k,g in t.groupby(['coin','ws','tok'])}
def sim(tlo=3,thi=20,askmin=0.55,askmax=0.99,skip=(0.90,0.98),ladder_min=0.94,thresh=0.10,slope=0.035,anchor=14.0,cov=0.5,improve=False):
    d=p[(p.tlk>=tlo)&(p.tlk<=thi)&(p['cov']>=cov)&p.fav_ask.notna()&(p.fav_asz>0)].copy()
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
            if n==0 and skip and skip[0]<=ask<=skip[1]: continue
            if n>0 and ask<ladder_min: continue
            tok='U' if r.side=='UP' else 'D'; e=tk.get((c,ws,tok))
            if e is None: continue
            tls,pxs,szs=e; m=(tls<=r.tlk)&(tls>r.tlk-FILLW)&(pxs<=ask+1e-9)
            if not m.any(): continue
            fpx=min(ask,float(pxs[m].max())) if improve else ask
            cap=min(CLIP,LADDER-spent); sh=min(cap/fpx, float(szs[m].sum()))      # tape-sized (bug #28)
            if sh<=0: continue
            fee=0.07*fpx*(1-fpx)*sh; pnl=(sh-fpx*sh-fee) if r.right else (-fpx*sh-fee)
            rows.append((c,ws,r.day,r.tlk,ask,fpx,sh,fpx*sh,pnl,r.right,n,r.est_bps))
            spent+=fpx*sh; last=r.tlk; n+=1
    return pd.DataFrame(rows,columns=['coin','ws','day','tl','ask','fpx','sh','cost','pnl','won','clip','est'])
def rep(f,label):
    if not len(f): print(label,'no fills'); return
    nd=f.day.nunique(); dy=f.groupby('day').pnl.sum()
    print(f'{label:30s} clips={len(f):5d} bars={f.groupby(["coin","ws"]).ngroups:4d} stake=${f.cost.sum():7.0f} pnl=${f.pnl.sum():8.2f} '
          f'roi={f.pnl.sum()/f.cost.sum()*100:6.2f}% win={f.won.mean():.4f} loss={int((~f.won).sum()):3d} ${f.pnl.sum()/nd:7.2f}/d worst=${dy.min():7.2f} pos={int((dy>0).sum())}/{len(dy)}')
base=sim(3,20); rep(base,'LIVE window tl 3-20')
for lo,hi in [(0,2),(0,20),(-2,20),(3,12),(0,12),(12,20)]:
    f=sim(lo,hi); rep(f,f'tl {lo}-{hi}')
print('\n-- the ADDED window alone (tl 0-2), by coin and day --')
f=sim(0,2)
if len(f):
    print(f.groupby('coin').agg(clips=('pnl','size'),stake=('cost','sum'),pnl=('pnl','sum'),win=('won','mean')).round(2).to_string())
    print(f.groupby('day').agg(clips=('pnl','size'),pnl=('pnl','sum')).round(2).to_string())
    print('ask dist of fills:',f.ask.round(2).value_counts().head(8).to_dict())
    print('LOO coin $/d:',{c:round(f[f.coin!=c].pnl.sum()/f.day.nunique(),2) for c in f.coin.unique()})
