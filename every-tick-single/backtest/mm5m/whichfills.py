"""Are the field's good fills the SAME population our sim fills on?

Our sim rests at the touch bid.  Split every real print by where the maker's
resting order sat relative to the pre-trade touch:
    at-touch   mpx == best bid of the maker's long token
    improved   mpx  > best bid  (the maker had posted a better price)
    deeper     mpx  < best bid  (level was swept through)
The DOWN book is the mirror of the UP book: bid_D = 1-ua, ask_D = 1-ub.
"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, agg, COINS

df = load(sys.argv[1:] or COINS)
df = df.dropna(subset=['ub', 'ua'])
# best bid of the token the maker ends up long
ltok_up = ~df.tbu.astype(bool)
df['lbid'] = np.where(ltok_up, df.ub, 1.0 - df.ua)
df['rel'] = (df.mpx - df.lbid).round(2)
df['where'] = np.select(
    [df.rel > 0.004, df.rel < -0.004], ['improved (better px)', 'deeper (swept through)'],
    default='at touch')

for win, lab in [((240, 297), 'OPEN WINDOW tl 240-297'), ((60, 240), 'mid-bar tl 60-240')]:
    s = df[(df.tl >= win[0]) & (df.tl <= win[1]) & (df.mpx >= .35) & (df.mpx <= .65)]
    print(f'\n===== {lab}, maker long .35-.65 =====')
    print(agg(s, 'where', minn=200).to_string())

print('\n===== OPEN WINDOW: at-touch fills only, by print size =====')
s = df[(df.tl >= 240) & (df.tl <= 297) & (df.mpx >= .35) & (df.mpx <= .65) & (df['where'] == 'at touch')]
s = s.copy(); s['szb'] = pd.cut(s.sz, [-1, 5, 20, 50, 150, 500, 1e9])
print(agg(s, 'szb', minn=200).to_string())
print(f"\nat-touch open-window aggregate: gross {np.average(s.mpnl, weights=s.sz)*100:+.3f} "
      f"net {np.average(s.net, weights=s.sz)*100:+.3f} c/sh on {s.sz.sum()/1e6:.2f}M shares")

print('\n===== how much of the flow is at-touch vs improved? (share of volume) =====')
o = df[(df.tl >= 240) & (df.tl <= 297) & (df.mpx >= .35) & (df.mpx <= .65)]
print((o.groupby('where').sz.sum() / o.sz.sum() * 100).round(1).to_string())
