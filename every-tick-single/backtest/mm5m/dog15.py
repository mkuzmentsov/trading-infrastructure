"""Is the 15m 'maker long .15-.30' edge REAL or the stale-snapshot artifact
that fooled us at 5m (§5: the '+3.44 swept-deep' bucket was the bid having
already moved)? Split by resting posture and check per-day stability."""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain15 import load, agg

df = load(sys.argv[1:] or ['btc', 'eth']).dropna(subset=['ub', 'ua', 'ubs', 'uas'])
lu = ~df.tbu.astype(bool)
df['lbid'] = np.where(lu, df.ub, 1.0 - df.ua)
df['rel'] = (df.mpx - df.lbid).round(2)
df['where'] = np.select([df.rel > .004, df.rel < -.004],
                        ['improved', 'deeper(swept)'], default='at touch')
d = df[(df.mpx >= .15) & (df.mpx <= .30)].copy()
print(f'DOG CELL (maker long .15-.30): {len(d):,} prints  {d.sz.sum()/1e6:.2f}M shares')
print('\n=== by resting posture (at-touch is the only capturable one) ===')
print(agg(d, 'where', minn=200).to_string())

t = d[d['where'] == 'at touch'].copy()
w = lambda x, c='mpnl': np.average(x[c], weights=x.sz) * 100
print(f"\nAT-TOUCH only: gross {w(t):+.3f}  net {w(t,'net'):+.3f} c/sh  "
      f"({t.sz.sum()/1e3:.0f}k shares)")
print('\n=== per day (at touch) ===')
pd_ = t.groupby('day').apply(lambda x: pd.Series({
    'kshares': x.sz.sum()/1e3, 'gross_c': w(x), 'net_c': w(x, 'net')}),
    include_groups=False)
print(pd_.round(2).to_string())
v = pd_.net_c.values
print(f'  mean {v.mean():+.3f}  pos {int((v>0).sum())}/{len(v)}')
print('\n=== per coin (at touch) ==='); print(agg(t, 'coin', minn=200).to_string())
print('\n=== by position in bar (at touch) ===')
t['fb'] = pd.cut(t.frac, [-.01, .2, .5, .8, 1.01],
                 labels=['last20%', 'mid', 'early', 'first20%'])
print(agg(t, 'fb', minn=200).to_string())
