"""Is the queue-imbalance edge stable, or an in-sample artifact?
Split the field's at-touch fills in our cell by time and by coin."""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, COINS

df = load(sys.argv[1:] or ['btc', 'eth', 'sol', 'xrp', 'bnb', 'doge'])
df = df.dropna(subset=['ub', 'ua', 'ubs', 'uas'])
lu = ~df.tbu.astype(bool)
df['lbid'] = np.where(lu, df.ub, 1.0 - df.ua)
df['rel'] = (df.mpx - df.lbid).round(2)
s = df[(df.tl >= 240) & (df.tl <= 297) & (df.mpx >= .44) & (df.mpx <= .56)
       & (df.rel.abs() < 0.005)].copy()
myq = np.where(lu[s.index], s.ubs, s.uas)
oppq = np.where(lu[s.index], s.uas, s.ubs)
s['imb'] = (myq - oppq) / np.clip(myq + oppq, 1, None)
s['hi'] = s.imb >= 0.4

w = lambda x, c='mpnl': np.average(x[c], weights=x.sz) * 100 if len(x) else np.nan
days = sorted(s.day.unique())
h1, h2 = set(days[:len(days)//2]), set(days[len(days)//2:])
print(f'at-touch fills in cell: {len(s):,}  ({s.sz.sum()/1e6:.2f}M shares)')
print(f"\n{'split':14s} {'n_hi':>8s} {'gross_hi':>9s} {'gross_lo':>9s} {'spread':>8s}")
for lab, sub in [('ALL', s), ('first half', s[s.day.isin(h1)]),
                 ('second half', s[s.day.isin(h2)])]:
    hi, lo = sub[sub.hi], sub[~sub.hi]
    print(f'{lab:14s} {len(hi):8d} {w(hi):+9.3f} {w(lo):+9.3f} {w(hi)-w(lo):+8.3f}')
print(f"\n{'coin':14s} {'n_hi':>8s} {'gross_hi':>9s} {'gross_lo':>9s} {'spread':>8s}")
for c in sorted(s.coin.unique()):
    sub = s[s.coin == c]; hi, lo = sub[sub.hi], sub[~sub.hi]
    if len(hi) < 200: continue
    print(f'{c:14s} {len(hi):8d} {w(hi):+9.3f} {w(lo):+9.3f} {w(hi)-w(lo):+8.3f}')
# per-day sign consistency of the HI bucket
pd_ = s[s.hi].groupby('day').apply(lambda x: w(x), include_groups=False)
print(f'\nHI-bucket gross per day: mean {pd_.mean():+.3f}  '
      f'pos {int((pd_>0).sum())}/{len(pd_)}  '
      f't={pd_.mean()/(pd_.std(ddof=1)/np.sqrt(len(pd_))):+.2f}')
