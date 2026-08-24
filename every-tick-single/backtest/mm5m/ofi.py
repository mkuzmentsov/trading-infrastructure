"""The last door: does the BOOK predict the pickoff?

Speed is blocked (190ms venue floor), patience is worse, hedging is structurally
impossible.  What remains is pre-emptively pulling quotes.  For that we need a
signal, observable at quote time, that separates good maker fills from toxic
ones.  Test the classic HFT candidates on the field's real at-touch fills:
  - book imbalance at the touch (our queue vs the opposite queue)
  - the size of the print that hits us
  - queue depth backing our own side
"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, agg, COINS

df = load(sys.argv[1:] or COINS)
df = df.dropna(subset=['ub', 'ua', 'ubs', 'uas'])
# restrict to the strategy's own cell: open window, coin-flip band, at the touch
ltok_up = ~df.tbu.astype(bool)
df['lbid'] = np.where(ltok_up, df.ub, 1.0 - df.ua)
df['rel'] = (df.mpx - df.lbid).round(2)
s = df[(df.tl >= 240) & (df.tl <= 297) & (df.mpx >= .44) & (df.mpx <= .56)
       & (df.rel.abs() < 0.005)].copy()
print(f'at-touch fills in the strategy cell: {len(s):,} prints, '
      f'{s.sz.sum()/1e6:.2f}M shares')
print(f'  gross {np.average(s.mpnl, weights=s.sz)*100:+.3f}  '
      f'net {np.average(s.net, weights=s.sz)*100:+.3f} c/sh')

# queue backing OUR side vs the other side, at the moment of the fill
# maker long UP -> our side is the UP bid (ubs); the opposite queue is uas
s['myq'] = np.where(ltok_up[s.index], s.ubs, s.uas)
s['oppq'] = np.where(ltok_up[s.index], s.uas, s.ubs)
s['imb'] = (s.myq - s.oppq) / (s.myq + s.oppq).clip(lower=1)

s['imbb'] = pd.qcut(s.imb, 6, duplicates='drop')
s['szb'] = pd.cut(s.sz, [-1, 5, 20, 50, 150, 500, 1e9])
s['myqb'] = pd.qcut(s.myq, 5, duplicates='drop')
for c, lab in [('imbb', 'book imbalance (our queue vs opposite)'),
               ('szb', 'size of the print that hit us'),
               ('myqb', 'depth backing our own side')]:
    print(f'\n=== by {lab} ===')
    print(agg(s, c, minn=300).to_string())
