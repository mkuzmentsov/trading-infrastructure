"""Calibrate the QUEUE model from data - the single number the whole strategy
hinges on: how fast does the size ahead of us at the touch evaporate?

At a level whose price is unchanged between two snapshots:
    dSize = adds - cancels - traded
Adds join BEHIND us, so what matters for our queue position is
    net_decay = max(0, -(dSize) - traded)      [shares/sec ahead of us that vanish]
Also measures how long a touch price survives (dwell), since a level that
moves away resets our position anyway.
"""
import gzip, json, os, sys, glob
from multiprocessing import Pool
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))


def scan(path):
    out = []      # (tl, side, size_before, dt, traded, decay, dwell_end)
    dwell = []    # (tl, seconds the touch price survived)
    try:
        with gzip.open(path, 'rt') as f:
            prev = {}
            level_start = {}
            for line in f:
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                ws, t, tl = d['ws'], d['t'], d['tl']
                if tl < 0 or tl > 301:
                    continue
                # traded volume per (token, price) in this interval
                tv = {}
                for ts, tok, px, sz, side in (d.get('trd') or []):
                    # maker long token / price  == the resting level consumed
                    upx = px if tok == 'U' else 1.0 - px
                    tbu = (side == 'BUY') == (tok == 'U')
                    ltok = 'D' if tbu else 'U'
                    lpx = round((1 - upx) if tbu else upx, 2)
                    tv[(ltok, lpx)] = tv.get((ltok, lpx), 0.0) + sz
                cur = {}
                for tok, b, bs in (('U', d['ub'], d['ubs']), ('D', d['db'], d['dbs'])):
                    if b is None:
                        continue
                    cur[tok] = (round(b, 2), bs or 0.0)
                p = prev.get(ws)
                if p:
                    dt = t - p['t']
                    if 0 < dt < 1.0:
                        for tok, (px, sz) in cur.items():
                            if tok not in p['lv']:
                                continue
                            ppx, psz = p['lv'][tok]
                            if ppx != px:                     # level moved
                                k = (ws, tok)
                                if k in level_start:
                                    dwell.append((p['tl'], t - level_start[k]))
                                level_start[k] = t
                                continue
                            traded = tv.get((tok, px), 0.0)
                            dsize = sz - psz
                            decay = max(0.0, -dsize - traded)
                            out.append((p['tl'], psz, dt, traded, decay))
                    prev[ws] = dict(t=t, tl=tl, lv=cur)
                else:
                    prev[ws] = dict(t=t, tl=tl, lv=cur)
                    for tok in cur:
                        level_start[(ws, tok)] = t
    except Exception as e:
        return None
    return out, dwell


if __name__ == '__main__':
    coin = sys.argv[1] if len(sys.argv) > 1 else 'btc'
    files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
    if len(sys.argv) > 2:
        files = files[:int(sys.argv[2])]
    pool = Pool(10)
    rows, dw = [], []
    for r in pool.imap_unordered(scan, files, chunksize=2):
        if r:
            rows.extend(r[0]); dw.extend(r[1])
    df = pd.DataFrame(rows, columns=['tl', 'size', 'dt', 'traded', 'decay'])
    df = df[df['size'] > 0]
    print(f'{coin}: {len(df):,} stable-level intervals over {len(files)} files')
    df['decay_ps'] = df.decay / df.dt
    df['trade_ps'] = df.traded / df.dt
    df['frac_ps'] = df.decay_ps / df['size']
    df['tlb'] = pd.cut(df.tl, [-1, 30, 60, 120, 240, 290, 301])
    print('\n=== queue decay at a STABLE touch level (per second) ===')
    g = df.groupby('tlb', observed=True).agg(
        n=('tl', 'size'), size_med=('size', 'median'),
        cancel_sh_s=('decay_ps', 'mean'), trade_sh_s=('trade_ps', 'mean'),
        cancel_frac_s=('frac_ps', 'mean'))
    g['halflife_s'] = np.log(2) / g.cancel_frac_s
    print(g.round(3).to_string())
    d = pd.DataFrame(dw, columns=['tl', 'dwell'])
    d['tlb'] = pd.cut(d.tl, [-1, 30, 60, 120, 240, 290, 301])
    print('\n=== how long does a touch PRICE survive (dwell, seconds) ===')
    print(d.groupby('tlb', observed=True).dwell.describe(
        percentiles=[.25, .5, .75, .9]).round(2).to_string())
