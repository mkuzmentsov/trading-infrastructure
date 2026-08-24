"""Mid-range (.40-.60) making: where in the bar is it survivable, and how thick
is the queue there?  Fine-grained first-90s map."""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, agg, COINS

df = load(sys.argv[1:] or COINS)
print(f'{len(df):,} prints, {df.day.nunique()} days')
mid = df[(df.mpx >= .35) & (df.mpx <= .65)].copy()
print(f'\nMID-RANGE prints (maker long .35-.65): {len(mid):,}  {mid.sz.sum()/1e6:.1f}M shares')

mid['tlb'] = pd.cut(mid.tl, [-1, 30, 60, 120, 180, 210, 240, 260, 275, 290, 297, 301])
print('\n=== mid-range maker economics by time-left ===')
print(agg(mid, 'tlb', minn=200).to_string())

mid['mpxb'] = pd.cut(mid.mpx, [.34, .42, .46, .50, .54, .58, .66])
print('\n=== first 60s of the bar (tl 240-297), by maker fill price ===')
fm = mid[(mid.tl >= 240) & (mid.tl <= 297)]
print(agg(fm, 'mpxb', minn=200).to_string())
print('\n=== same, per coin ===')
print(agg(fm, 'coin', minn=100).to_string())
print('\n=== per day (all coins, tl 240-297, .35-.65) ===')
pd_ = fm.groupby('day').apply(lambda x: pd.Series({
    'kshares': x.sz.sum()/1e3,
    'gross_c': np.average(x.mpnl, weights=x.sz)*100,
    'net_c': np.average(x.net, weights=x.sz)*100}), include_groups=False)
print(pd_.round(2).to_string())
d = pd_.net_c.values
print(f'  mean {d.mean():+.3f} c/sh  std {d.std(ddof=1):.3f}  t={d.mean()/(d.std(ddof=1)/np.sqrt(len(d))):+.2f}  pos days {(d>0).sum()}/{len(d)}')

# what does the book look like at the open?  (queue thickness = our real constraint)
print('\n=== book state near the open (btc snapshots) ===')
