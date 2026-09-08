import mm, lw2, pandas as pd, numpy as np
D={c:mm.load_coin(c) for c in mm.COINS}
base=dict(QMIN=0.98,IMP=1,TL_HI=30.,TL_LO=2.,SIZE=50.,LAT=0.2,SCAN=0.4,EVMAX=1.0)
d=pd.concat([lw2.run(c,*D[c],**base) for c in mm.COINS],ignore_index=True)
d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
bar=d.groupby(['coin','ws']).agg(pnl=('pnl','sum'),sh=('f','sum'),q=('q','mean'),win=('win','max'))
L=bar[bar.win==0]
print(f'bars filled {len(bar)}  shares {int(bar.sh.sum())}  total PnL ${bar.pnl.sum():.2f} (6 days)')
print(f'LOSING bars {len(L)} ({len(L)/len(bar)*100:.2f}%)  losing shares {int(L.sh.sum())} '
      f'({L.sh.sum()/bar.sh.sum()*100:.3f}%)  loss $ {L.pnl.sum():.2f}')
print(f'winning bars PnL ${bar[bar.win==1].pnl.sum():.2f}')
p=len(L)/len(bar); a,b=len(L)+.5,len(bar)-len(L)+.5
from scipy import stats
lo,hi=stats.beta.ppf([.025,.975],a,b)
q=(d.q*d.f).sum()/d.f.sum(); be=(1-q)/1.0
print(f'\nmean fill price {q:.4f} -> BREAK-EVEN loss rate {be*100:.3f}% (per share)')
sl=L.sh.sum()/bar.sh.sum()
print(f'observed share loss rate {sl*100:.3f}%   bar loss rate {p*100:.3f}% [Jeffreys 95% {lo*100:.2f}-{hi*100:.2f}%]')
print(f'=> at the 95% UPPER bar-loss bound the lane is {"POSITIVE" if hi<be else "NEGATIVE"}')
print('\nlosing bars:'); print(L.sort_values('pnl').head(12).round(3).to_string())
rng=np.random.default_rng(0); v=bar.pnl.values
bs=np.array([rng.choice(v,len(v),replace=True).sum() for _ in range(4000)])/6
print(f'\nbootstrap over bars: $/day mean {bs.mean():+.1f}  5th pct {np.percentile(bs,5):+.1f}  '
      f'P(>0) {(bs>0).mean():.3f}')
day=d.assign(day=pd.to_datetime(d.ws,unit='s',utc=True).dt.date).groupby('day').pnl.sum()
print('\nper day $:',{str(k):round(x,2) for k,x in day.items()})
# leave-one-coin-out
print('\nleave-one-COIN-out $/day:')
for c in mm.COINS:
    s=bar.drop(index=c,level=0).pnl.sum()/6; print(f'  drop {c:5s} -> {s:+7.2f}')
print('\nleave-one-DAY-out $/day:')
for k in day.index:
    print(f'  drop {k} -> {(day.sum()-day[k])/5:+7.2f}')
