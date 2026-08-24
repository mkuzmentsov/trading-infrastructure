"""The honest terrain map: what does the MAKER side of every real print earn?

No fill model, no queue model - these are fills that actually happened.
maker PnL/share = (upx - upwon) if taker_bought_up else (upwon - upx)
rebate/share    = 0.20 * 0.07 * p * (1-p)      [crypto maker rebate, 20% of taker fee]
"""
import sys, glob, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, 'cache', 'prints')
REB = 0.20 * 0.07


def load(coin, days=None):
    fs = sorted(glob.glob(os.path.join(CACHE, f'{coin}-*.parquet')))
    if days:
        fs = [f for f in fs if os.path.basename(f).split('-')[1][:8] in days]
    df = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    df['coin'] = coin
    return df


def enrich(df):
    # maker's realized PnL per share, and the price the MAKER transacted at
    #  tbu (taker bought UP)  -> maker SOLD up  at upx : pnl = upx - upwon
    #  ~tbu                   -> maker BOUGHT up at upx : pnl = upwon - upx
    df['mpnl'] = np.where(df.tbu, df.upx - df.upwon, df.upwon - df.upx)
    # price the maker's own leg trades at (what he paid / received, 0..1)
    df['mpx'] = np.where(df.tbu, 1.0 - df.upx, df.upx)   # maker sells UP == buys DOWN at 1-upx
    df['reb'] = REB * df.upx * (1.0 - df.upx)
    df['net'] = df.mpnl + df.reb
    df['notional'] = df.sz * df.mpx
    return df


def agg(df, by, minn=200):
    g = df.groupby(by, observed=True)
    out = pd.DataFrame({
        'prints': g.size(),
        'shares': g.sz.sum(),
        'mpnl_c': g.apply(lambda x: np.average(x.mpnl, weights=x.sz) * 100, include_groups=False),
        'reb_c': g.apply(lambda x: np.average(x.reb, weights=x.sz) * 100, include_groups=False),
    })
    out['net_c'] = out.mpnl_c + out.reb_c
    out['maker_$'] = out.net_c / 100 * out.shares
    return out[out.prints >= minn]


if __name__ == '__main__':
    coins = sys.argv[1:] or ['btc']
    df = pd.concat([enrich(load(c)) for c in coins], ignore_index=True)
    print(f'total prints {len(df):,}  shares {df.sz.sum():,.0f}  '
          f'maker notional ${df.notional.sum():,.0f}')
    print(f'\n=== HEADLINE: maker side, all prints ===')
    w = lambda col: np.average(df[col], weights=df.sz) * 100
    print(f'  gross maker PnL  {w("mpnl"):+.3f} c/share')
    print(f'  rebate           {w("reb"):+.3f} c/share')
    print(f'  NET              {w("net"):+.3f} c/share')
    print(f'  total maker net  ${(df.net * df.sz).sum():,.0f} over {len(df.ws.unique()):,} bars')

    df['tlb'] = pd.cut(df.tl, [-1, 10, 20, 30, 45, 60, 90, 120, 180, 240, 301])
    df['pxb'] = pd.cut(df.upx, [-.01, .05, .15, .3, .45, .55, .7, .85, .95, 1.01])
    print('\n=== by time-left ===')
    print(agg(df, 'tlb').to_string())
    print('\n=== by UP price ===')
    print(agg(df, 'pxb').to_string())
    print('\n=== by taker direction ===')
    print(agg(df, 'tbu').to_string())
    if len(coins) > 1:
        print('\n=== by coin ===')
        print(agg(df, 'coin').to_string())
