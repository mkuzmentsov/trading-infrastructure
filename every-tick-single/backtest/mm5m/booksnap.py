"""Snapshot-level book state: queue thickness & spread through the bar,
plus the open-price puzzle (the market does NOT open at 0.50)."""
import gzip, json, os, sys, glob
from multiprocessing import Pool
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))


def scan(path):
    rows = []
    opens = []
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                ub, ua, tl = d['ub'], d['ua'], d['tl']
                if ub is None or ua is None:
                    continue
                if int(tl * 2) % 2:          # ~1 Hz sample
                    continue
                rows.append((tl, ub, ua, d['ubs'] or 0, d['uas'] or 0,
                             d['dbs'] or 0, d['das'] or 0,
                             d['lead_bps'] if d['lead_bps'] is not None else np.nan))
                if tl > 298.5:
                    opens.append((d['ws'], (ub + ua) / 2))
    except Exception as e:
        return None
    return rows, opens


if __name__ == '__main__':
    coin = sys.argv[1] if len(sys.argv) > 1 else 'btc'
    files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
    pool = Pool(10)
    rows, opens = [], []
    for r in pool.imap_unordered(scan, files, chunksize=4):
        if r:
            rows.extend(r[0]); opens.extend(r[1])
    df = pd.DataFrame(rows, columns=['tl', 'ub', 'ua', 'ubs', 'uas', 'dbs', 'das', 'lead'])
    df['spread'] = (df.ua - df.ub) * 100
    df['mid'] = (df.ub + df.ua) / 2
    # queue at the touch of whichever side is the favourite / underdog
    df['favq'] = np.where(df.mid > .5, df.ubs, df.dbs)     # bid queue on the favourite
    df['dogq'] = np.where(df.mid > .5, df.dbs, df.ubs)
    df['tlb'] = pd.cut(df.tl, [-1, 30, 60, 120, 180, 240, 270, 290, 297, 301])
    print(f'{coin}: {len(df):,} 1Hz snapshots')
    print('\n=== spread & touch-queue through the bar ===')
    g = df.groupby('tlb', observed=True).agg(
        n=('tl', 'size'), spread_c=('spread', 'median'),
        spread_p90=('spread', lambda x: np.percentile(x, 90)),
        favq_med=('favq', 'median'), favq_p25=('favq', lambda x: np.percentile(x, 25)),
        dogq_med=('dogq', 'median'), mid_med=('mid', 'median'))
    print(g.round(2).to_string())
    print('\n=== spread distribution, first 60s ===')
    f = df[df.tl >= 240]
    print((f.spread.round().value_counts(normalize=True).sort_index().head(8) * 100).round(1).to_string())
    print('\n=== the OPEN price puzzle: mid at tl~300 ===')
    o = pd.DataFrame(opens, columns=['ws', 'mid']).drop_duplicates('ws')
    print(f'  bars {len(o)}  mid at open: median {o.mid.median():.3f}  '
          f'|mid-0.5|>0.05 in {(o.mid.sub(.5).abs() > .05).mean()*100:.1f}% of bars, '
          f'>0.15 in {(o.mid.sub(.5).abs() > .15).mean()*100:.1f}%')
    print(o.mid.describe().round(3).to_string())
