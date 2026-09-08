"""POST-CLOSE FLIP WINDOW: after the venue flips the tick (mostly post-close), how much winner
SELL flow arrives while the best bid is still on the 0.01 grid (nobody has improved yet)?  A
0.991 bid posted at the flip instant front-runs the whole 0.99 queue for exactly that window."""
import pandas as pd, numpy as np
F=pd.read_parquet('a12_tick.parquet')
r=pd.read_parquet('pq/res.parquet'); r['winT']=np.where(r.win=='UP','U','D'); r['ws']=r.ws.astype('int64')
b=pd.read_parquet('pq/bookev.parquet',columns=['coin','ws','tok','t','b0']); b['ws']=b.ws.astype('int64')
b=b.merge(r[['coin','ws','winT','t']].rename(columns={'t':'tres'}),on=['coin','ws']); b=b[(b.tok==b.winT)]
b=b.merge(F,on=['coin','ws']); b=b[(b.t>=b.t_tick)&(b.t<=b.tres)]
# first time after flip that best bid goes off-grid (someone improved)
imp=b[(np.round(b.b0*1000)%10)!=0].groupby(['coin','ws']).t.min().rename('t_imp')
F2=F.merge(r[['coin','ws','winT','t']].rename(columns={'t':'tres'}),on=['coin','ws']).merge(imp,on=['coin','ws'],how='left')
F2['win_end']=F2[['t_imp','tres']].min(axis=1); F2['window']=F2.win_end-F2.t_tick
print(f'flip bars with resolution: {len(F2)}; someone improves after flip: {F2.t_imp.notna().mean()*100:.1f}%; time flip->first improver (s): p25/50/75',np.nanpercentile(F2.t_imp-F2.t_tick,[25,50,75]).round(1))
t=pd.read_parquet('pq/trades.parquet'); t['ws']=t.ws.astype('int64'); t=t.merge(r[['coin','ws','winT']],on=['coin','ws'])
w=t[(t.tok==t.winT)&(t.side=='SELL')].merge(F2[['coin','ws','t_tick','win_end','tres']],on=['coin','ws'])
inwin=w[(w.mts>=w.t_tick+0.2)&(w.mts<=w.win_end)&(w.px<=0.991)]
post=inwin[inwin.mts>inwin.ws+300]; pre=inwin[inwin.mts<=inwin.ws+300]
for lab,x in [('ALL (pre+post close)',inwin),('post-close only',post),('pre-close only',pre)]:
    cap=x.groupby(['coin','ws']).sz.sum().clip(upper=50)
    print(f'{lab:22s}: winner SELL prints <=0.991 inside [flip, first-improver): prints {len(x)} sh/day {x.sz.sum()/6:.0f} pool $/day at 0.9c {x.sz.sum()*0.009/6:+.1f} | 50sh/bar cap: bars/day {len(cap)/6:.1f} $/day {cap.sum()*0.009/6:+.2f}')
print('per coin sh/day (all):',(inwin.groupby('coin').sz.sum()/6).round(0).to_dict())
