"""Calibrate a fair-value model for the OPEN window and test whether it adds
information beyond the book's own mid.

In the first minute the TWAP settlement window (tl<=62) has not started, so
fair value is a pure diffusion estimate:
      p_up = Phi( lead_bps / sigma(tl) )
Calibrate sigma(tl) against realised outcomes, then ask the only question that
matters for skewing quotes: does (p_hat - mid) predict where the mid GOES?
"""
import gzip, json, os, sys, glob
from multiprocessing import Pool
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))


def scan(path):
    wins, rows = {}, []
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    d = json.loads(line); wins[d['ws']] = 1 if d['win'] == 'UP' else 0; continue
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                ub, ua, lead, tl = d['ub'], d['ua'], d['lead_bps'], d['tl']
                if ub is None or ua is None or lead is None or not (0 <= tl <= 301):
                    continue
                rows.append((d['ws'], round(d['t'], 1), tl, lead, (ub + ua) / 2))
    except Exception:
        return None
    return wins, rows


if __name__ == '__main__':
    coin = sys.argv[1] if len(sys.argv) > 1 else 'btc'
    files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
    pool = Pool(10); wins = {}; rows = []
    for r in pool.imap_unordered(scan, files, chunksize=4):
        if r: wins.update(r[0]); rows.extend(r[1])
    df = pd.DataFrame(rows, columns=['ws', 't', 'tl', 'lead', 'mid'])
    df['won'] = df.ws.map(wins)
    df = df.dropna(subset=['won'])
    df = df.sort_values(['ws', 't']).drop_duplicates(['ws', 't'])
    print(f'{coin}: {len(df):,} snapshots, {df.ws.nunique():,} bars')

    # ---- calibrate sigma(tl): P(up) = Phi(lead/sigma) ----
    df['tlb'] = (df.tl // 15 * 15).astype(int)
    cal = []
    for tlb, g in df.groupby('tlb'):
        if len(g) < 5000: continue
        # sigma that best matches realised outcomes (grid search on log-loss)
        best, bs = None, 1e9
        for s in np.arange(0.5, 40, 0.25):
            p = np.clip(norm.cdf(g.lead.values / s), 1e-6, 1-1e-6)
            ll = -np.mean(g.won.values*np.log(p) + (1-g.won.values)*np.log(1-p))
            if ll < bs: bs, best = ll, s
        pm = np.clip(g.mid.values, 1e-6, 1-1e-6)
        llm = -np.mean(g.won.values*np.log(pm) + (1-g.won.values)*np.log(1-pm))
        cal.append((tlb, len(g), best, bs, llm))
    c = pd.DataFrame(cal, columns=['tl', 'n', 'sigma_bps', 'logloss_model', 'logloss_mid'])
    print('\n=== sigma(tl) calibration: model vs the BOOK MID as predictors ===')
    print(c.round(4).to_string(index=False))

    sig = dict(zip(c.tl, c.sigma_bps))
    df['sigma'] = df.tlb.map(sig)
    df = df.dropna(subset=['sigma'])
    df['phat'] = norm.cdf(df.lead / df.sigma)
    df['edge'] = df.phat - df.mid

    # ---- does (phat - mid) predict where the mid goes? ----
    print('\n=== does (p_hat - mid) predict the FUTURE mid? (open window tl 240-297) ===')
    o = df[(df.tl >= 240) & (df.tl <= 297)].copy()
    o['fut'] = o.groupby('ws').mid.shift(-20)      # ~2s ahead at 0.1s grid... t rounded to 0.1
    for h, lab in [(10, '1s'), (30, '3s'), (100, '10s')]:
        o[f'f{h}'] = o.groupby('ws').mid.shift(-h)
        s = o.dropna(subset=[f'f{h}'])
        d = s[f'f{h}'] - s.mid
        eb = pd.qcut(s.edge, 7, duplicates='drop')
        g = s.groupby(eb, observed=True).apply(
            lambda x: pd.Series({'n': len(x), 'edge': x.edge.mean(),
                                 f'd_mid_{lab}': (x[f'h' if False else f'f{h}'] - x.mid).mean()}),
            include_groups=False)
        print(f'\n  horizon {lab}:  corr(edge, dmid)={np.corrcoef(s.edge, d)[0,1]:+.4f}')
        print(g.round(4).to_string())
    # and against the OUTCOME
    print('\n=== predicting the OUTCOME: mid alone vs mid+model (open window) ===')
    s = o.dropna(subset=['won'])
    for name, p in [('book mid', s.mid), ('model phat', s.phat), ('0.5*(mid+phat)', 0.5*(s.mid+s.phat))]:
        pp = np.clip(p, 1e-6, 1-1e-6)
        ll = -np.mean(s.won*np.log(pp) + (1-s.won)*np.log(1-pp))
        print(f'  {name:16s} logloss {ll:.5f}  brier {np.mean((pp-s.won)**2):.5f}')
