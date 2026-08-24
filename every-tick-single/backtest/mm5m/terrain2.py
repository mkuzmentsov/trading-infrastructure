"""Terrain map v2 - label-invariant cuts + robustness (per-day, per-coin).

Under the UP<->DOWN relabelling every maker PnL is invariant, so only
label-invariant features are legitimate strategy variables:
  mpx   = the price the MAKER's own leg traded at
  tl    = time left
  long_leader = maker ended up long the side spot momentum currently favours
"""
import sys, glob, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache', 'prints')
REB = 0.20 * 0.07
COINS = ['btc', 'eth', 'sol', 'xrp', 'bnb', 'doge', 'hype']


def load(coins):
    out = []
    for c in coins:
        for f in sorted(glob.glob(os.path.join(CACHE, f'{c}-*.parquet'))):
            d = pd.read_parquet(f)
            d['coin'] = c
            d['day'] = os.path.basename(f).split('-')[1][:8]
            out.append(d)
    df = pd.concat(out, ignore_index=True)
    # maker economics
    df['mpnl'] = np.where(df.tbu, df.upx - df.upwon, df.upwon - df.upx)
    df['mpx'] = np.where(df.tbu, 1.0 - df.upx, df.upx)      # maker's own fill price
    df['reb'] = REB * df.upx * (1.0 - df.upx)
    df['net'] = df.mpnl + df.reb
    # label-invariant: is the maker long the momentum leader?
    #   maker is long UP iff taker sold UP (~tbu)
    maker_long_up = ~df.tbu.astype(bool)
    ll = np.where(df.lead > 0, maker_long_up, ~maker_long_up).astype('float32')
    ll[~(df.lead.abs() >= 0.2)] = np.nan       # no clear leader / missing spot
    df['long_leader'] = ll
    df['spread'] = df.ua - df.ub
    return df


def agg(df, by, minn=500):
    g = df.groupby(by, observed=True)
    sz = g.sz.sum()
    out = pd.DataFrame({
        'prints': g.size(),
        'kshares': sz / 1e3,
        'gross_c': g.apply(lambda x: np.average(x.mpnl, weights=x.sz) * 100, include_groups=False),
        'reb_c': g.apply(lambda x: np.average(x.reb, weights=x.sz) * 100, include_groups=False),
    })
    out['net_c'] = out.gross_c + out.reb_c
    out['net_$/day'] = out.net_c / 100 * sz / df.day.nunique()
    return out[out.prints >= minn].round(3)


if __name__ == '__main__':
    coins = sys.argv[1:] or COINS
    df = load(coins)
    print(f'{len(df):,} prints, {df.sz.sum()/1e6:.1f}M shares, {df.day.nunique()} days, coins={coins}')
    df['tlb'] = pd.cut(df.tl, [-1, 15, 30, 60, 90, 120, 150, 180, 210, 240, 270, 285, 296, 301])
    df['mpxb'] = pd.cut(df.mpx, [-.01, .03, .08, .15, .25, .35, .45, .55, .65, .75, .85, .92, .97, 1.01])

    print('\n=== by coin ===');            print(agg(df, 'coin').to_string())
    print('\n=== by time-left (all coins) ==='); print(agg(df, 'tlb').to_string())
    print('\n=== by maker fill price ==='); print(agg(df, 'mpxb').to_string())
    print('\n=== maker long the momentum leader? ===')
    print(agg(df.dropna(subset=['long_leader']), 'long_leader').to_string())
    print('\n=== first minute (tl>240) x coin: per-day robustness ===')
    fm = df[df.tl > 240]
    print(agg(fm, ['coin'], minn=100).to_string())
    piv = fm.groupby(['day', 'coin'], observed=True).apply(
        lambda x: np.average(x.net, weights=x.sz) * 100, include_groups=False).unstack()
    print('\nnet c/share, tl>240, by day x coin:')
    print(piv.round(2).to_string())
