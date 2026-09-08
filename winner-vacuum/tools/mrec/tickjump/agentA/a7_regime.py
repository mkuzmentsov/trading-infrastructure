"""HARDENING: the 0.001 tick is a PER-TOKEN venue REGIME that only unlocks after a
tick_size_change (§24/§56: 0.991 was rejected 'invalid price, max 0.99' in coarse bars).
Restrict the tick-jump fills to instants where the fine regime is PROVEN for that market:
 evidence = earliest of (rb.tick==0.001 reconcile) OR (any off-0.01-grid price on either token's
 book in bookev b0/a0) OR (any off-grid level in lad10, tl<=26).  Both tokens of a market share
 the regime (mirror book), so evidence on either token counts."""
import pandas as pd, numpy as np
rb=pd.read_parquet('pq/rb.parquet'); rb=rb[rb.tick.notna()&(rb.tick.astype(float)<=0.0011)]
e1=rb.groupby(['coin','ws']).t.min().rename('t_rb')
b=pd.read_parquet('pq/bookev.parquet',columns=['coin','ws','t','b0','a0'])
off=lambda x:(x.notna())&((np.round(x*1000)%10)!=0)&(x>0.0005)&(x<0.9995)
bo=b[off(b.b0)|off(b.a0)]; e2=bo.groupby(['coin','ws']).t.min().rename('t_be'); del b,bo
L=pd.read_parquet('lad10.parquet'); cols=[c for c in L.columns if c.endswith('p')]
m=np.zeros(len(L),bool)
for c in cols: m|=off(L[c]).values
e3=L[m].groupby(['coin','ws']).t.min().rename('t_lad'); del L
E=pd.concat([e1,e2,e3],axis=1); E['t_fine']=E.min(axis=1); E=E.reset_index()
E['ws']=E.ws.astype('int64')
print('bars with ANY fine-tick evidence:',len(E),' via rb',E.t_rb.notna().sum(),' via bookev',E.t_be.notna().sum(),' via lad10',E.t_lad.notna().sum())
E.to_parquet('a7_regime.parquet',index=False)
# apply to the tick-jump fills
for lab in ('G0','G2','G1G2'):
    d=pd.read_parquet(f'a2_{lab}.parquet'); d['ws']=d.ws.astype('int64')
    d=d.merge(E[['coin','ws','t_fine']],on=['coin','ws'],how='left')
    d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    d['proven']=d.t_fine.notna()&(d.t>=d.t_fine)
    d['everfine']=d.t_fine.notna()
    for k,mm_ in [('ALL',np.ones(len(d),bool)),('regime proven AT fill',d.proven.values),('regime proven any time in bar',d.everfine.values)]:
        x=d[mm_]; 
        if not len(x): print(lab,k,'none'); continue
        bb=x.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'),w=('win','max'))
        ps=bb.p.sum()/bb.s.sum(); se=np.sqrt(((bb.p-ps*bb.s)**2).sum())/bb.s.sum()
        print(f'{lab:5s} {k:32s} bars {len(bb):5d} sh {int(bb.s.sum()):7d} net {ps*100:+.3f}+/-{se*100:.3f} $/d {bb.p.sum()/6:+7.1f} losing bars {int((bb.w==0).sum())} | LOO-btc $/d {bb.drop(index="btc",level=0).p.sum()/6:+6.1f}')
    print(f'      share of fills (shares) with regime proven at fill: {d.f[d.proven].sum()/d.f.sum()*100:.1f}%; ever in bar: {d.f[d.everfine].sum()/d.f.sum()*100:.1f}%')
# how early is the regime proven relative to the fill?
d=pd.read_parquet('a2_G2.parquet'); d['ws']=d.ws.astype('int64'); d=d.merge(E[['coin','ws','t_fine']],on=['coin','ws'],how='left')
d['lead']=d.t-d.t_fine
print('G2 fills: t_fill - t_fine (s), among proven-ever: p10/50/90',np.nanpercentile(d.lead,[10,50,90]))
