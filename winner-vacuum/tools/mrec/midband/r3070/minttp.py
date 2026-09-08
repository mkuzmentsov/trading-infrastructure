"""MINT a pair at open, rest an ASK at TP on BOTH tokens (front of queue), hold residual to
resolution.  Fill = taker BUY pressure on the token at >= TP (own-token space: BUY prints on
tok, plus SELL prints on the other tok at 1-px), tape-size capped.  Outcomes per bar:
   neither fills -> pair redeems $1 -> 0 ; one fills -> TP - 1 ; both fill -> 2*TP - 1."""
import pandas as pd, numpy as np
PQ='/private/tmp/claude-501/-Users-maxkuzmentsov-development-projects-my-hummingbot-hummingbot-infra/b78fafe5-77e0-41c9-af8e-fc68c051450c/scratchpad/pq'
t=pd.read_parquet(f'{PQ}/trades.parquet'); r=pd.read_parquet(f'{PQ}/res.parquet')
t=t.merge(r[['coin','ws','win']],on=['coin','ws']); t['tl']=t.ws+300-t.mts
opp={'U':'D','D':'U'}
b=t[t.side=='BUY'][['coin','ws','tok','px','sz','tl','win']].copy()
s=t[t.side=='SELL'][['coin','ws','tok','px','sz','tl','win']].copy(); s['tok']=s.tok.map(opp); s['px']=1-s.px
bp=pd.concat([b,s])                       # taker BUY pressure on `tok` at `px`
bars=r[['coin','ws','win']].copy(); bars['day']=pd.to_datetime(bars.ws,unit='s',utc=True).dt.date
print('bars',len(bars))
def run(TP,N=50,window='inbar',chop=None):
    w=bp[(bp.tl>0)] if window=='inbar' else bp[bp.tl>-300]
    v=w[w.px>=TP-1e-9].groupby(['coin','ws','tok']).sz.sum().unstack('tok').reindex(
        pd.MultiIndex.from_frame(bars[['coin','ws']])).fillna(0.0)
    sU=np.minimum(N,v['U'].values); sD=np.minimum(N,v['D'].values)
    wU=(bars.win.values=='UP').astype(float)
    pnl=TP*(sU+sD)+(N-sU)*wU+(N-sD)*(1-wU)-N+0.2*0.07*TP*(1-TP)*(sU+sD)
    d=bars.assign(sU=sU,sD=sD,pnl=pnl)
    if chop is not None: d=d[chop]
    both=((d.sU>0)&(d.sD>0)).mean(); one=((d.sU>0)^(d.sD>0)).mean(); none=((d.sU==0)&(d.sD==0)).mean()
    day=d.groupby('day').pnl.sum(); per=d.pnl
    se=per.std()/np.sqrt(len(per))
    print(f'TP {TP:.2f} N{N} {window:7s} bars={len(d):5d} both={both*100:5.2f}% one={one*100:5.1f}% none={none*100:5.1f}% '
          f'pnl/bar={per.mean()*100:+6.2f}c ±{se*100:4.2f}  $/day={day.mean():+8.1f}  days+={int((day>0).sum())}/{len(day)}')
    return d
for TP in (0.90,0.95,0.97,0.98,0.99):
    run(TP)
print('--- incl. post-close prints (tl>-300) ---')
for TP in (0.97,0.99): run(TP,window='post')
print('--- per coin, TP 0.99 in-bar ---')
d=run(0.99)
print(d.groupby('coin').apply(lambda g:pd.Series({'both%':((g.sU>0)&(g.sD>0)).mean()*100,'one%':((g.sU>0)^(g.sD>0)).mean()*100,'c/bar':g.pnl.mean()*100,'$/d':g.pnl.sum()/6}),include_groups=False).round(2).to_string())
# "chop" proxy: bars where the max buy-pressure price on BOTH tokens stayed <0.90 until tl<=60 (undecided late)
late=bp[(bp.tl>60)&(bp.px>=0.90)].groupby(['coin','ws']).size()
undec=~pd.MultiIndex.from_frame(bars[['coin','ws']]).isin(late.index)
print('--- gate: no token ≥0.90 before tl 60 ("late chop") ---')
for TP in (0.97,0.99): run(TP,chop=undec)
