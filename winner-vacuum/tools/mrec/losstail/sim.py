"""House-cell vacmaker replay on the 9-day tape, with bid-drop / est-thinness features."""
import os,sys,numpy as np,pandas as pd
PQ='/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq'
os.environ['MREC_PQ']=PQ
sys.path.insert(0,'/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/winner-vacuum/tools/mrec')
import lib
CACHE='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/5f718a63-35c5-4e2b-85fb-af9cff0c8e41/scratchpad/A'

def panel():
    f=f'{CACHE}/pan.parquet'
    if os.path.exists(f): return pd.read_parquet(f)
    p=pd.read_parquet(f'{PQ}/panelflow2.parquet')
    # bid lags: fav_bid K seconds EARLIER (tl larger)
    for K in (5,6,10,20):
        bb=p[['coin','ws','tlk','fav_bid']].copy(); bb['tlk']=bb.tlk-K
        p=p.merge(bb.rename(columns={'fav_bid':f'fb{K}'}),on=['coin','ws','tlk'],how='left')
        p[f'dB{K}']=p.fav_bid-p[f'fb{K}']
        p[f'rB{K}']=p[f'dB{K}']/p[f'fb{K}'].replace(0,np.nan)
        # same for our-side ASK (placebo / alternative)
        aa=p[['coin','ws','tlk','fav_ask']].copy(); aa['tlk']=aa.tlk-K
        p=p.merge(aa.rename(columns={'fav_ask':f'fa{K}'}),on=['coin','ws','tlk'],how='left')
        p[f'dA{K}']=p.fav_ask-p[f'fa{K}']
    p.to_parquet(f,index=False)
    return p

def tape():
    t=lib.load_trades()
    t=t[(t.side=='BUY')&(t.tl>=-2)&(t.tl<=60)]
    tk={}
    for (c,ws,tok),g in t.groupby(['coin','ws','tok']):
        o=np.argsort(-g.tl.values)
        tk[(c,ws,tok)]=(g.tl.values[o],g.px.values[o],g.sz.values[o])
    return tk

CLIP=24.0; LADDER=48.0; GAP=8.0; FILLW=0.4
def sim(p,tk,veto=None,tlo=3,thi=20,askmin=0.55,askmax=0.99,skip=(0.90,0.98),
        ladder_min=0.94,thresh=0.10,slope=0.035,anchor=14.0,covmin=0.5,
        clip=CLIP,ladder=LADDER,fillw=FILLW,improve=False,szcap=False,coins=None):
    d=p[(p.tlk>=tlo)&(p.tlk<=thi)&(p['cov']>=covmin)&p.fav_ask.notna()&(p.fav_asz>0)]
    if coins: d=d[d.coin.isin(coins)]
    d=d[d.est_bps.abs()>=(thresh+slope*np.maximum(0,d.tlk-anchor))]
    d=d[(d.fav_ask>=askmin)&(d.fav_ask<=askmax)]
    d=d.sort_values(['coin','ws','tlk'],ascending=[True,True,False])
    cols=['coin','ws','day','tlk','fav_ask','fav_asz','fav_a1p','fav_a1s','fav_a2p','fav_a2s',
          'fav_bid','est_bps','right','side','cov','vol','mf10','mf30','dp10','dp30',
          'dB5','dB6','dB10','dB20','rB5','rB6','rB10','rB20','dA5','dA6','dA10','dA20','hr']
    rows=[]; out=[]
    for (c,ws),g in d.groupby(['coin','ws'],sort=False):
        spent=0.0; last=None; n=0
        for r in g.itertuples():
            if spent>=ladder: break
            if last is not None and (last-r.tlk)<GAP: continue
            ask=r.fav_ask
            if n==0:
                if skip and skip[0]<=ask<=skip[1]: continue
            else:
                if ask<ladder_min: continue
            thr=thresh+slope*max(0.0,r.tlk-anchor)
            marg=abs(r.est_bps)-thr
            rec=dict(coin=c,ws=ws,day=r.day,tl=r.tlk,ask=ask,bid=r.fav_bid,est=r.est_bps,
                     marg=marg,right=bool(r.right),clipn=n,cov=getattr(r,'cov',np.nan),vol=r.vol,hr=r.hr,
                     mf10=r.mf10,mf30=r.mf30,dp10=r.dp10,dp30=r.dp30,
                     dB5=r.dB5,dB6=r.dB6,dB10=r.dB10,dB20=r.dB20,
                     rB5=r.rB5,rB6=r.rB6,rB10=r.rB10,rB20=r.rB20,
                     dA6=r.dA6,dA10=r.dA10,dA20=r.dA20)
            if veto is not None and veto(rec): continue
            tok='U' if r.side=='UP' else 'D'
            e=tk.get((c,ws,tok))
            if e is None: continue
            tls,pxs,szs=e
            tref=r.tl if r.tl==r.tl else float(r.tlk)
            m=(tls<=tref)&(tls>tref-fillw)&(pxs<=ask+1e-9)
            if not m.any(): continue
            printed=float(szs[m].sum())
            budget=min(clip,ladder-spent)
            if improve:
                lv=[(min(ask,float(pxs[m].max())),1e9)]
            else:
                lv=[(ask,r.fav_asz),(r.fav_a1p,r.fav_a1s),(r.fav_a2p,r.fav_a2s)]
                lv=[(float(px),float(sz)) for px,sz in lv if px==px and sz==sz and sz>0 and px<=askmax+1e-9]
                lv.sort()
            sh=0.0; cost=0.0
            for px,sz in lv:
                if budget-cost<=1e-9: break
                take=min(sz,(budget-cost)/px)
                sh+=take; cost+=take*px
            if szcap and sh>printed:
                k=printed/sh; sh*=k; cost*=k
            if sh<=0: continue
            fpx=cost/sh
            fee=0.07*fpx*(1-fpx)*sh
            pnl=(sh-cost-fee) if r.right else (-cost-fee)
            rec.update(sh=sh,cost=cost,fpx=fpx,pnl=pnl,printed=printed)
            rows.append(rec); spent+=cost; last=r.tlk; n+=1
    return pd.DataFrame(rows)

def rep(f,label,ndays=None):
    if len(f)==0: print(f'{label}: EMPTY'); return
    nd=ndays or f.day.nunique(); nb=f.groupby(['coin','ws']).ngroups
    bar=f.groupby(['coin','ws']).pnl.sum()
    print(f'{label}: clips={len(f)} bars={nb} lossclips={(f.pnl<0).sum()} lossbars={(bar<0).sum()} '
          f'stake=${f.cost.sum():.0f} pnl=${f.pnl.sum():.2f} roi={f.pnl.sum()/f.cost.sum()*100:.2f}% '
          f'win={f.right.mean():.3f} ${f.pnl.sum()/nd:.2f}/day lossbars/day={(bar<0).sum()/nd:.2f}')
