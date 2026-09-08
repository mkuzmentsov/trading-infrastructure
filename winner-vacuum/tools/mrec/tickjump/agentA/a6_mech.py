"""Lead 4: venue mechanics to abuse.  (A) tick_size_change: when does the tick flip, how fast do
others use the fine grid, and is there a transient?  (B) post-close tape: what prints between
T+0 and resolution, and against whom?  (C) who BUYS the favourite at 0.999 late (demand for a
minted-pair 0.999 ask)?"""
import mm, pandas as pd, numpy as np
r=pd.read_parquet('pq/res.parquet'); r['winT']=np.where(r.win=='UP','U','D')
rb=pd.read_parquet('pq/rb.parquet')
print('=== (A) rb.tick values ===');print(rb.tick.value_counts(dropna=False).to_string())
rb['tl']=rb.ws+300-rb.t
x=rb[rb.tick.notna()].sort_values(['coin','ws','tok','t'])
x['prev']=x.groupby(['coin','ws','tok']).tick.shift()
ch=x[(x.prev.notna())&(x.tick!=x.prev)]
print(f'tick changes observed in REST reconciles: {len(ch)}; by (prev->new):'); print(ch.groupby(['prev','tick']).size().to_string())
print('tl at change: p10/50/90',np.percentile(ch.tl,[10,50,90]) if len(ch) else None)
# how fast do others use the fine grid: per bar, first snapshot with fav bid>=0.96 vs first off-grid fav bid
s=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','t','tl','ub','db'])
s=s[s.tl.between(0,120)]
fav=np.maximum(s.ub.fillna(0),s.db.fillna(0)); s['fb']=fav
g=s[s.fb>=0.96].groupby(['coin','ws'])
first96=g.t.min(); off=s[(s.fb>=0.96)&((np.round(s.fb*1000)%10)!=0)].groupby(['coin','ws']).t.min()
j=pd.concat([first96.rename('t96'),off.rename('toff')],axis=1)
j['lag']=j.toff-j.t96
print(f'\nbars with fav bid>=0.96 in last 120s: {len(j)}; bars where an off-grid (0.001) best bid EVER appears: {j.toff.notna().sum()} ({j.toff.notna().mean()*100:.1f}%)')
print('lag from first >=0.96 to first off-grid best bid (s): p25/50/75',np.nanpercentile(j.lag,[25,50,75]))
# what off-grid values appear
og=s[(s.fb>=0.96)&((np.round(s.fb*1000)%10)!=0)].fb.round(3).value_counts().head(6); print('off-grid fav bid values:',og.to_dict())
del s
# (B) post-close tape
t=pd.read_parquet('pq/trades.parquet').merge(r[['coin','ws','winT','t']].rename(columns={'t':'tres'}),on=['coin','ws'])
t['tl']=t.ws+300-t.mts; pc=t[(t.tl<0)&(t.mts<=t.tres)].copy()
pc['isw']=(pc.tok==pc.winT); pc['secs_after']=-pc.tl
print(f'\n=== (B) POST-CLOSE prints (T+0 .. resolution): {len(pc)} prints, {int(pc.sz.sum())} sh over 6 days; secs after close p50 {pc.secs_after.median():.1f} ===')
pc['cls']=np.where(pc.isw,'WINNER','LOSER')
print(pc.groupby(['cls','side']).agg(n=('sz','size'),sh=('sz','sum'),px_med=('px','median'),px_p10=('px',lambda x:x.quantile(.1)),px_p90=('px',lambda x:x.quantile(.9))).round(3).to_string())
w=pc[pc.isw&(pc.side=='SELL')]
print('\nWINNER sold post-close (a resting winner bid would be hit): by price band, shares/day:')
print((w.groupby(pd.cut(w.px,[0,0.5,0.9,0.98,0.99,0.995,0.999,1.0001])).sz.sum()/6).round(0).to_string())
l=pc[(~pc.isw)&(pc.side=='BUY')]
print('LOSER bought post-close (a resting loser ASK from a minted pair would be lifted): by price, sh/day:')
print((l.groupby(pd.cut(l.px,[0,0.001,0.005,0.01,0.02,0.05,0.5,1.0])).sz.sum()/6).round(0).to_string())
# (C) buys of the favourite at >=0.999 (== sells of the underdog at <=0.001) in tl 0-30 and post-close
b=t[(t.side=='BUY')&(t.px>=0.9985)]; b['isw']=(b.tok==b.winT)
for lab,m in [('tl 0-30',b.tl.between(0,30)),('tl 30-120',b.tl.between(30,120)),('post-close',b.tl<0)]:
    x=b[m]; print(f'\n(C) BUY prints at >=0.999, {lab}: prints {len(x)} sh/day {x.sz.sum()/6:.0f}  P(token wins) {(x.sz*x.isw).sum()/max(x.sz.sum(),1):.4f}  per coin sh/day {(x.groupby("coin").sz.sum()/6).round(0).to_dict()}')
sd=t[(t.side=='SELL')&(t.px<=0.0015)]; sd['isw']=(sd.tok==sd.winT)
x=sd[sd.tl.between(0,30)]; print(f'(C mirror) SELL prints at <=0.001 tl 0-30: prints {len(x)} sh/day {x.sz.sum()/6:.0f} P(token wins) {(x.sz*x.isw).sum()/max(x.sz.sum(),1):.4f}')
