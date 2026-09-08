"""Break-even rewards subsidy per policy: pool $/day per coin that flips net >= 0.
reward $/day = pool * share(place,v) * presence, presence = ss_band / (eligible window share-seconds
of a permanently-resting 50sh two-sided quote = 2 sides * 50sh * 210s * bars/day)."""
import pandas as pd, numpy as np
sc=pd.read_csv('sweep_scored_all.csv'); rs=pd.read_csv('rewshare.csv')
AUG={'btc':10000,'eth':1666.67,'sol':1666.67,'hype':1666.67,'xrp':1666.67,'bnb':833.33,'doge':833.33}
bars_day=9833/6/7   # per coin
full_ss=2*50*210*bars_day   # share-seconds/day/coin of a 50sh two-sided quote resting the whole eligible window
rows=[]
for _,r in sc.iterrows():
    pl='edge15' if 'edge15' in r.lab else ('edge05' if 'edge05' in r.lab else 'join')
    if 'size20' in r.lab: continue
    pres=(r.ss_band_k*1000/7)/full_ss          # per coin presence fraction of the eligible window
    for v in (0.015,0.045):
        sh=rs[(rs.v==v)&(rs.place==pl)].set_index('coin').share
        aug=sum(AUG[c]*sh[c]*pres for c in AUG)  # $/day, Aug-2026 pools, 7 coins
        cost=-r.usd_day
        # pool needed per coin (uniform) to break even: cost = pool * sum(share_c) * pres
        need=cost/(sh.sum()*pres) if pres>0 and sh.sum()>0 else np.nan
        rows.append(dict(lab=r.lab,v=v,cost_usd_day=round(cost,1),presence=round(pres,3),
                         aug_pool_reward=round(aug,1),net_with_aug=round(aug-cost,1),
                         breakeven_pool_per_coin=round(need,0)))
d=pd.DataFrame(rows); d.to_csv('breakeven.csv',index=False); print(d.to_string(index=False))
