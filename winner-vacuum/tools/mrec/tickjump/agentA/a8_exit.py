"""After a tick-jump fill at q~0.991, could we SELL at 0.999 to a late buyer instead of holding to
settlement?  Census: BUY prints on the same token at >=0.999 after our fill instant, before close."""
import pandas as pd, numpy as np
t=pd.read_parquet('pq/trades.parquet'); t['ws']=t.ws.astype('int64')
buys=t[(t.side=='BUY')&(t.px>=0.9985)]; buys['tl']=buys.ws+300-buys.mts
for lab in ('G0','G2'):
    d=pd.read_parquet(f'a2_{lab}.parquet'); d['ws']=d.ws.astype('int64')
    d['tok']=d.side
    g=d.groupby(['coin','ws','tok']).agg(t=('t','min'),f=('f','sum'),q=('q','mean'),win=('win','max')).reset_index()
    j=g.merge(buys[['coin','ws','tok','mts','px','sz']],on=['coin','ws','tok'],how='left')
    j=j[(j.mts>j.t)&(j.mts<=j.ws+300)]
    dem=j.groupby(['coin','ws','tok']).sz.sum().rename('dem')
    g=g.merge(dem,on=['coin','ws','tok'],how='left'); g['dem']=g.dem.fillna(0)
    g['sold']=np.minimum(g.f,g.dem)
    hold=(g.f*((g.win-g.q)+0.2*0.07*g.q*(1-g.q))).sum()
    # exit: sold shares realise (0.999-q)+rebate on both legs; unsold held
    ex=(g.sold*(0.999-g.q+2*0.2*0.07*g.q*(1-g.q))+(g.f-g.sold)*((g.win-g.q)+0.2*0.07*g.q*(1-g.q))).sum()
    print(f'{lab}: filled bar-tokens {len(g)}; bars with ANY >=0.999 buy demand after our fill: {(g.dem>0).mean()*100:.1f}%; shares exitable {g.sold.sum()/g.f.sum()*100:.1f}%; PnL hold ${hold:.1f} vs exit-when-possible ${ex:.1f} (6d)')
