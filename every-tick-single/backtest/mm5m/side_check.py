"""Validate: does trd[4] side == TAKER side? Compare px to the PRE-trade book."""
import gzip, json, sys, collections
import numpy as np

path = sys.argv[1]
prev = {}          # ws -> last cur snap book
stats = collections.Counter()
rel = collections.defaultdict(list)
seen = set()

with gzip.open(path, 'rt') as f:
    for line in f:
        if '"role":"cur"' not in line:
            continue
        d = json.loads(line)
        ws = d['ws']
        trd = d.get('trd')
        if trd:
            p = prev.get(ws)
            if p and p['ua'] is not None and p['ub'] is not None:
                for ts, tok, px, sz, side in trd:
                    k = (ts, tok, px, sz, side)
                    if k in seen:
                        continue
                    seen.add(k)
                    # express everything in UP-token terms
                    if tok == 'U':
                        upx, ubid, uask = px, p['ub'], p['ua']
                    else:
                        upx, ubid, uask = 1 - px, p['ub'], p['ua']
                    # a taker BUY of D == taker SELL of U
                    taker_buys_up = (side == 'BUY') == (tok == 'U')
                    stats[(side, tok)] += 1
                    if taker_buys_up:
                        rel['buy_up_minus_ask'].append(round(upx - uask, 4))
                    else:
                        rel['sell_up_minus_bid'].append(round(upx - ubid, 4))
        prev[ws] = d

for k, v in rel.items():
    a = np.array(v)
    print(f"{k}: n={len(a)} mean={a.mean():+.4f} median={np.median(a):+.4f} "
          f"pct_at_or_beyond={(a >= -1e-9).mean() if 'ask' in k else (a <= 1e-9).mean():.3f} "
          f"p05={np.percentile(a,5):+.3f} p95={np.percentile(a,95):+.3f}")
print(stats)
