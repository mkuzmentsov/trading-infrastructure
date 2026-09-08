import pandas as pd, numpy as np, lw3, mm
PAN='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq/panel.parquet'
p=pd.read_parquet(PAN,columns=['coin','ws','tlk','est_bps','cov','side','ub','db','fav_bid','evage'])
for lab in ('G0','G1','G2','G1G2'):
    d=pd.read_parquet(f'a2_{lab}.parquet')
    d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    b=d.groupby(['coin','ws']).agg(pnl=('pnl','sum'),sh=('f','sum'),q=('q','mean'),tl=('tl','max'),tlmin=('tl','min'),side=('side','first'),win=('win','max')).reset_index()
    L=b[b.win==0].copy()
    L['tlk']=L.tl.round().astype(int)
    L=L.merge(p,left_on=['coin','ws','tlk'],right_on=['coin','ws','tlk'],how='left')
    # est at tl=20 and tl=10 for context
    for k in (25,15,5):
        x=p[p.tlk==k][['coin','ws','est_bps','side']].rename(columns={'est_bps':f'est{k}','side':f'side{k}'})
        L=L.merge(x,on=['coin','ws'],how='left')
    print(f'\n===== {lab}: losing bars {len(L)} of {len(b)}  total pnl ${b.pnl.sum():.1f}  loss ${L.pnl.sum():.1f} =====')
    if len(L): print(L[['coin','ws','side_x','q','sh','pnl','tl','tlmin','est_bps','cov','side_y','est25','side25','est15','side15','est5','side5']].round(3).to_string(index=False))
