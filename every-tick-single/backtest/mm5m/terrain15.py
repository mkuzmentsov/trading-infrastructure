"""Does the 15m maker side look better than 5m? Same methodology as terrain.py
(every real print, maker side, no fill model), buckets scaled to a 900s bar.

5m reference numbers to beat:
  ALL prints            -0.010 c/sh net   (gross -0.209 + rebate 0.199)
  first 20% of bar      +0.411
  mid-bar               -0.297
  imbalance spread      -1.27 (thin) .. +2.64 (thick)
"""
import sys, os, glob
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache', 'prints')
REB = 0.20 * 0.07
BAR = 900.0


def load(coins):
    out = []
    for c in coins:
        for f in sorted(glob.glob(os.path.join(CACHE, f'{c}-mrec15m-*.parquet'))):
            d = pd.read_parquet(f); d['coin'] = c
            d['day'] = os.path.basename(f).split('-')[2][:8]
            out.append(d)
    df = pd.concat(out, ignore_index=True)
    df['mpnl'] = np.where(df.tbu, df.upx - df.upwon, df.upwon - df.upx)
    df['mpx'] = np.where(df.tbu, 1.0 - df.upx, df.upx)
    df['reb'] = REB * df.upx * (1.0 - df.upx)
    df['net'] = df.mpnl + df.reb
    df['frac'] = df.tl / BAR                      # 1.0 = bar open, 0 = close
    return df


def agg(df, by, minn=300):
    g = df.groupby(by, observed=True)
    sz = g.sz.sum()
    o = pd.DataFrame({
        'prints': g.size(), 'kshares': sz / 1e3,
        'gross_c': g.apply(lambda x: np.average(x.mpnl, weights=x.sz) * 100, include_groups=False),
        'reb_c': g.apply(lambda x: np.average(x.reb, weights=x.sz) * 100, include_groups=False)})
    o['net_c'] = o.gross_c + o.reb_c
    o['net_$/day'] = o.net_c / 100 * sz / df.day.nunique()
    return o[o.prints >= minn].round(3)


if __name__ == '__main__':
    coins = sys.argv[1:] or ['btc', 'eth']
    df = load(coins)
    w = lambda c: np.average(df[c], weights=df.sz) * 100
    print(f'{len(df):,} prints, {df.sz.sum()/1e6:.1f}M shares, {df.day.nunique()} days, '
          f'{df.groupby(["coin","ws"]).ngroups} bars')
    print(f'\n=== HEADLINE (15m, all prints) ===')
    print(f'  gross {w("mpnl"):+.3f}   rebate {w("reb"):+.3f}   NET {w("net"):+.3f} c/share')
    print(f'  [5m was: gross -0.209  rebate +0.199  NET -0.010]')

    df['fb'] = pd.cut(df.frac, [-.01, .05, .2, .4, .6, .8, .95, 1.01],
                      labels=['last5%', '5-20%', '20-40%', '40-60%', '60-80%',
                              '80-95%', 'first5%'])
    print('\n=== by position in bar (first5% = just after open) ===')
    print(agg(df, 'fb').to_string())
    df['mpxb'] = pd.cut(df.mpx, [-.01, .15, .3, .45, .55, .7, .85, 1.01])
    print('\n=== by maker fill price ===')
    print(agg(df, 'mpxb').to_string())

    # the strategy cell: early bar + coin-flip band, split by queue imbalance
    df = df.dropna(subset=['ub', 'ua', 'ubs', 'uas'])
    lu = ~df.tbu.astype(bool)
    df['lbid'] = np.where(lu, df.ub, 1.0 - df.ua)
    df['rel'] = (df.mpx - df.lbid).round(2)
    s = df[(df.frac >= .8) & (df.frac <= .99) & (df.mpx >= .44) & (df.mpx <= .56)
           & (df.rel.abs() < .005)].copy()
    myq = np.where(lu[s.index], s.ubs, s.uas); oppq = np.where(lu[s.index], s.uas, s.ubs)
    s['imb'] = (myq - oppq) / np.clip(myq + oppq, 1, None)
    print(f'\n=== STRATEGY CELL: first 20% of bar, .44-.56, at touch ===')
    print(f'  {len(s):,} prints  {s.sz.sum()/1e3:.0f}k shares  '
          f'gross {np.average(s.mpnl, weights=s.sz)*100:+.3f}  '
          f'net {np.average(s.net, weights=s.sz)*100:+.3f} c/sh')
    if len(s) > 2000:
        s['ib'] = pd.qcut(s.imb, 6, duplicates='drop')
        print(agg(s, 'ib', minn=100).to_string())
