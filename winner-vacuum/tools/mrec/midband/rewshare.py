"""Reward-share estimator: what fraction of a per-market daily pool would a 50sh two-sided
quote have earned, sampled 1/min over the reward-eligible window (tl<=250, config lag), using
the Aug scoring rule  w = ((v-s)/v)^2 * size, s=|px-mid|, min order 50, Q_min = min(bid,ask side).
Field Q from the recorded top-3 ladders on both sides (U bids + U asks; by the mirror identity
that is the whole two-token book).  Reports per coin for v=1.5c and v=4.5c."""
import pandas as pd, numpy as np
COINS=['btc','eth','sol','xrp','bnb','doge','hype']
def Q(levels,mid,v):
    q=0.0
    for p,z in levels:
        if p!=p or z!=z or z<50: continue
        s=abs(p-mid)
        if s<v: q+=((v-s)/v)**2*z
    return q
rows=[]
for c in COINS:
    s=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','t','tl','ub','ua','evage']+
        [f'{sd}{i}{k}' for sd in ('ubd','uad') for i in range(3) for k in ('p','s')],filters=[('coin','==',c)])
    s=s[(s.tl<=250)&(s.tl>=5)&(s.evage<1)&s.ub.notna()&s.ua.notna()]
    s['mid']=(s.ub+s.ua)/2
    s=s[(s.mid>=0.20)&(s.mid<=0.80)]
    # 1/min sampling: take one row per (ws, minute)
    s['mn']=(s.tl//60).astype(int); s=s.groupby(['ws','mn']).head(1)
    for v in (0.015,0.045):
        fb=np.array([Q([(getattr(r,f'ubd{i}p'),getattr(r,f'ubd{i}s')) for i in range(3)],r.mid,v) for r in s.itertuples()])
        fa=np.array([Q([(getattr(r,f'uad{i}p'),getattr(r,f'uad{i}s')) for i in range(3)],r.mid,v) for r in s.itertuples()])
        for pl,off in (('join',None),('edge05',0.005),('edge15',0.015)):
            if pl=='join': sU=s.mid.values-s.ub.values; sD=s.ua.values-s.mid.values
            else:
                qb=np.floor((s.mid.values-off)/0.01+1e-9)*0.01; qa=np.ceil((s.mid.values+off)/0.01-1e-9)*0.01
                sU=s.mid.values-qb; sD=qa-s.mid.values
            ours_b=np.where(sU<v,((v-sU)/v)**2*50,0.0); ours_a=np.where(sD<v,((v-sD)/v)**2*50,0.0)
            ours=np.minimum(ours_b,ours_a)
            field=np.minimum(fb,fa)          # field Q_min proxy (aggregate; overstates a single maker)
            share=np.where(ours+field>0,ours/(ours+field),0.0)
            rows.append(dict(coin=c,v=v,place=pl,samples=len(s),our_w=round(ours.mean(),2),
                             field_q=round(field.mean(),1),share=round(share.mean(),4),
                             share_med=round(np.median(share),4),pct_zero=round((ours==0).mean(),3)))
    print(c,flush=True)
d=pd.DataFrame(rows); d.to_csv('rewshare.csv',index=False)
print(d.to_string(index=False))
