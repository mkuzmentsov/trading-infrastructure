"""POST-CLOSE winner bid lane (snipe-rest's lane) re-measured on the TAPE with the regime filter.
From T+2 (winner known, 99.98%) to resolution: keep a bid at winner_best_bid+0.001 (<=0.999) and
take SELL prints at <= q.  PnL = (1-q)*sh + rebate.  Then restrict to regime-proven instants."""
import pandas as pd, numpy as np
E=pd.read_parquet('a7_regime.parquet')
r=pd.read_parquet('pq/res.parquet'); r['winT']=np.where(r.win=='UP','U','D'); r['ws']=r.ws.astype('int64')
b=pd.read_parquet('pq/bookev.parquet',columns=['coin','ws','tok','t','b0','b0s']); b['ws']=b.ws.astype('int64')
t=pd.read_parquet('pq/trades.parquet'); t['ws']=t.ws.astype('int64')
t=t.merge(r[['coin','ws','winT','t']].rename(columns={'t':'tres'}),on=['coin','ws'])
pc=t[(t.mts>t.ws+302)&(t.mts<=t.tres)&(t.tok==t.winT)&(t.side=='SELL')].sort_values('mts')
b=b.merge(r[['coin','ws','winT','t']].rename(columns={'t':'tres'}),on=['coin','ws']); b=b[(b.tok==b.winT)&(b.t>=b.ws+300)&(b.t<=b.tres)].sort_values('t')
m=pd.merge_asof(pc[['coin','ws','mts','px','sz']].rename(columns={'mts':'t'}).sort_values('t'),b[['coin','ws','t','b0','b0s']],on='t',by=['coin','ws'],direction='backward',tolerance=5.0)
m=m[m.b0.notna()]
m['q']=np.minimum(np.round(m.b0+0.001,4),0.999)
m['hit']=m.px<=m.q+1e-9
m=m.merge(E[['coin','ws','t_fine']],on=['coin','ws'],how='left'); m['proven']=m.t_fine.notna()&(m.t>=m.t_fine)
print(f'post-close winner SELL prints with a book: {len(m)}, sh {int(m.sz.sum())}; hit our q: {m.hit.mean()*100:.1f}% prints, {m.sz[m.hit].sum()/m.sz.sum()*100:.1f}% sh')
print('best bid at print (winner): ',m.b0.round(3).value_counts().head(6).to_dict())
for k,mm_ in [('ALL',m.hit),('regime proven at print',m.hit&m.proven),('b0<=0.99 (coarse-looking)',m.hit&(m.b0<=0.9905)),('b0>=0.995',m.hit&(m.b0>=0.9945))]:
    x=m[mm_]; pnl=(x.sz*(1-x.q+0.2*0.07*x.q*(1-x.q))).sum()
    cap=x.groupby(['coin','ws']).sz.sum().clip(upper=50)
    print(f'  {k:28s} prints {len(x):5d} sh/day {x.sz.sum()/6:8.0f} mean q {(x.q*x.sz).sum()/max(x.sz.sum(),1):.4f} pool $/day {pnl/6:+7.1f} | at 50sh/bar cap: bars/day {len(cap)/6:.0f} $/day {(cap*(1-x.groupby(["coin","ws"]).q.mean())).sum()/6:+.1f}')
print('per coin sh/day (hit):',(m[m.hit].groupby('coin').sz.sum()/6).round(0).to_dict())
