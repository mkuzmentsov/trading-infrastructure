"""The candidate pool: maker LONG the favourite at .85-.95, mid-bar.
Mechanic: ONE resting BUY on the favourite at .85-.95 captures both flows
(a taker selling the favourite, and a taker buying the dog - same queue,
the PM book is fully mirrored).  Question: is the edge stable & conditionable?
"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, agg, COINS

df = load(sys.argv[1:] or COINS)
POOL = df[(df.mpx >= .85) & (df.mpx <= .96) & (df.tl >= 45) & (df.tl <= 250)].copy()
print(f'pool: {len(POOL):,} prints, {POOL.sz.sum()/1e6:.2f}M shares, '
      f'{POOL.sz.sum()/1e3/POOL.day.nunique():.0f}k shares/day field-wide')
w = lambda x, c='net': np.average(x[c], weights=x.sz) * 100
print(f'pool net {w(POOL):+.3f} c/sh   gross {w(POOL,"mpnl"):+.3f}   '
      f'field $/day {w(POOL)/100*POOL.sz.sum()/POOL.day.nunique():+,.0f}')
print(f'win rate of the maker leg: {np.average(POOL.upwon.where(~POOL.tbu.astype(bool), 1-POOL.upwon), weights=POOL.sz):.4f} '
      f'vs implied {np.average(POOL.mpx, weights=POOL.sz):.4f}')

print('\n=== per coin ===');  print(agg(POOL, 'coin', minn=100).to_string())
print('\n=== per day (btc) ===')
b = POOL[POOL.coin == 'btc']
print(b.groupby('day').apply(lambda x: pd.Series({
    'kshares': x.sz.sum()/1e3, 'net_c': w(x), 'gross_c': w(x, 'mpnl')}), include_groups=False).round(2).to_string())

# conditioning on OBSERVABLE state at quote time
POOL['ldb'] = pd.cut(POOL.lead.abs(), [-1, .5, 1, 2, 4, 8, 1e9])
# does our long side agree with the spot lead? (maker long UP iff ~tbu)
mlu = ~POOL.tbu.astype(bool)
POOL['agree'] = np.where(POOL.lead.abs() < .3, 'flat', np.where((POOL.lead > 0) == mlu, 'long the SPOT leader', 'long the spot LAGGARD'))
POOL['szb'] = pd.cut(POOL.sz, [-1, 10, 50, 200, 1000, 1e9])
POOL['tlb2'] = pd.cut(POOL.tl, [44, 60, 90, 120, 180, 250])
POOL['mpxb2'] = pd.cut(POOL.mpx, [.84, .87, .90, .93, .96])
for c in ['ldb', 'agree', 'szb', 'tlb2', 'mpxb2']:
    print(f'\n=== by {c} ==='); print(agg(POOL, c, minn=200).to_string())
print('\n=== price x agreement ===')
print(agg(POOL, ['mpxb2', 'agree'], minn=200).to_string())
