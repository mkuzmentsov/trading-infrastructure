"""Outcome-label validation + 2D terrain (tl x maker price) + tail decomposition."""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terrain2 import load, agg, COINS

coins = sys.argv[1:] or COINS
df = load(coins)

# ---- CONTROL 1: outcome labels sane? near the bell the market must agree ----
print('=== outcome-label validation ===')
for lo, hi in [(0, 5), (5, 15), (15, 60), (60, 300)]:
    s = df[(df.tl >= lo) & (df.tl < hi)]
    print(f'  tl {lo:3d}-{hi:3d}: mean upx {s.upx.mean():.4f}  mean upwon {s.upwon.mean():.4f}  '
          f'corr {np.corrcoef(s.upx, s.upwon)[0,1]:+.3f}')
print(f'  UP win rate over bars: {df.groupby(["coin","ws"]).upwon.first().mean():.4f}')

# ---- CONTROL 2: does the drift explain the aggregate? shuffle outcomes per bar ----
rng = np.random.default_rng(0)
bars = df.groupby(['coin', 'ws']).upwon.first()
flip = pd.Series(rng.random(len(bars)) < 0.5, index=bars.index)
f = df.set_index(['coin', 'ws']).index.map(flip)
mpnl_ctrl = np.where(f, -df.mpnl.values, df.mpnl.values)
print(f'  control (random per-bar outcome flip) gross: '
      f'{np.average(mpnl_ctrl, weights=df.sz)*100:+.3f} c/sh  (real {np.average(df.mpnl, weights=df.sz)*100:+.3f})')

# ---- 2D: tl x maker fill price ----
df['tlb'] = pd.cut(df.tl, [-1, 30, 60, 120, 180, 240, 296, 301],
                   labels=['0-30', '30-60', '60-120', '120-180', '180-240', '240-296', '296+'])
df['mpxb'] = pd.cut(df.mpx, [-.01, .05, .15, .30, .45, .55, .70, .85, .95, 1.01],
                    labels=['<.05', '.05-.15', '.15-.30', '.30-.45', '.45-.55', '.55-.70', '.70-.85', '.85-.95', '>.95'])

def cell(x, what):
    if what == 'net':  return np.average(x.net, weights=x.sz) * 100
    if what == 'sh':   return x.sz.sum() / 1e3
    return len(x)

for what, name in [('net', 'NET c/share'), ('sh', 'kshares')]:
    piv = df.groupby(['tlb', 'mpxb'], observed=True).apply(lambda x: cell(x, what), include_groups=False).unstack()
    print(f'\n=== {name}: time-left (rows) x maker fill price (cols) ===')
    print(piv.round(2 if what == 'net' else 0).to_string())

# ---- tail decomposition: who initiates the 0.85-0.97 maker-long fills? ----
print('\n=== maker long .85-.97 : decomposition by taker action ===')
t = df[(df.mpx >= .85) & (df.mpx <= .97)].copy()
t['taker_action'] = np.where(t.tbu, 'taker BUYS the cheap dog (<=.15)', 'taker SELLS the favourite (>=.85)')
print(agg(t, ['taker_action'], minn=100).to_string())
print('\n  ...and by time-left:')
print(agg(t, ['taker_action', 'tlb'], minn=100).to_string())
