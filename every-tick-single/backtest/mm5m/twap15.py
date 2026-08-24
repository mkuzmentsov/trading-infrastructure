"""Does the vacmaker TWAP-recon edge exist on 15m markets — and is there SUPPLY?

15m settles on the SAME mechanism as 5m: Chainlink TWAP, 60s lookback (verified
via gamma cryptoMarketConfig). The TWAP window is the same ABSOLUTE 60s, so the
recon math at a given tl is identical; only the competition differs. 5m is
crowded (the whale takes 14 bars/3h we don't); 15m may be quieter.

Replicates twapedge's live gate:
  est(tl) = mean(lead_bps) over [T-62, T-tl]        (partial TWAP, what we know)
  coverage = (62-tl)/59  >= 0.5
  |est| >= 0.5 + 0.035*max(0, tl-14) bps            (the time-scaled gate)
  buy the implied winner as TAKER if 0.55 <= ask <= 0.99
Settle vs the RES outcome.

⚠️ lead_bps is BINANCE spot vs bar open; settlement is CHAINLINK. They diverge
only on ~0bps ties (ledger #19: the proxy runs 2-3x PESSIMISTIC on flip rate),
so these accuracy numbers UNDERSTATE live. Conservative for a go/no-go.
"""
import gzip, json, os, sys, glob, collections
from multiprocessing import Pool
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
CLIP = 8.0            # $ per clip, matches live
FEE = 0.07


def scan(args):
    path, bar_s = args
    bars = collections.defaultdict(list)   # ws -> [(tl, lead, ua, uas, da, das)]
    wins = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    d = json.loads(line); wins[d['ws']] = 1 if d['win'] == 'UP' else 0
                    continue
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                tl = d['tl']
                if tl is None or not (2.0 <= tl <= 70.0):
                    continue
                if d.get('lead_bps') is None:
                    continue
                bars[d['ws']].append((tl, d['lead_bps'], d['ua'], d['uas'],
                                      d['da'], d['das']))
    except Exception:
        return None
    out = []
    for ws, rows in bars.items():
        if ws not in wins:
            continue
        rows.sort(key=lambda r: -r[0])          # time order (tl descending)
        out.append((ws, wins[ws], rows))
    return out


def evaluate(barlist, tl_lo, tl_hi, thresh0, slope, cov_min, ask_lo, ask_hi):
    res = []
    for ws, won, rows in barlist:
        # partial-TWAP estimate at each snapshot, over [T-62, T-tl]
        acc = []
        fired = False
        for tl, lead, ua, uas, da, das in rows:
            if tl > 62.0:
                continue
            acc.append(lead)
            if fired or not (tl_lo <= tl <= tl_hi):
                continue
            cov = (62.0 - tl) / 59.0
            if cov < cov_min:
                continue
            est = sum(acc) / len(acc)
            if abs(est) < thresh0 + slope * max(0.0, tl - 14.0):
                continue
            up_side = est > 0
            ask = ua if up_side else da
            if ask is None or not (ask_lo <= ask <= ask_hi):
                continue
            sh = CLIP / ask
            fee = FEE * ask * (1 - ask) * sh
            w = won if up_side else (1 - won)
            res.append((ws, tl, est, ask, sh, w, sh * (w - ask) - fee))
            fired = True
    return res


if __name__ == '__main__':
    import itertools
    combos = [(f'{c} 5m ', c, '', '-mrec', 300) for c in ('btc', 'eth')] + \
             [(f'{c} 15m', c, '-mrec15m', '-mrec', 900) for c in ('btc', 'eth')]
    for label, coin, sub, pref, bar_s in combos:
        files = sorted(glob.glob(os.path.join(MREC, coin + sub,
                                              f'{coin}{pref}-*.jsonl.gz')))
        if not files:
            print(f'{label}: NO FILES'); continue
        pool = Pool(10)
        allbars = []
        for r in pool.imap_unordered(scan, [(f, bar_s) for f in files], chunksize=4):
            if r: allbars.extend(r)
        pool.close()
        days = len({ws // 86400 for ws, _, _ in allbars})
        print(f'\n=== {label}: {len(allbars)} resolved bars over {days} days ===')
        print(f"  {'gate':26s} {'clips':>6s} {'/day':>6s} {'acc':>6s} "
              f"{'avg_ask':>8s} {'PnL':>9s} {'$/clip':>7s}")
        for name, tl_lo, tl_hi, th, sl in (
                ('live gate (tl3-30)', 3, 30, 0.5, 0.035),
                ('tl 3-20 only', 3, 20, 0.5, 0.035),
                ('tl 3-14 (strict)', 3, 14, 0.5, 0.0),
                ('loose thresh 0.3', 3, 30, 0.3, 0.035)):
            r = evaluate(allbars, tl_lo, tl_hi, th, sl, 0.5, 0.55, 0.99)
            if not r:
                print(f"  {name:26s} {0:6d}"); continue
            pnl = sum(x[6] for x in r); acc = np.mean([x[5] for x in r])
            print(f"  {name:26s} {len(r):6d} {len(r)/max(1,days):6.1f} "
                  f"{acc*100:5.1f}% {np.mean([x[3] for x in r]):8.3f} "
                  f"{pnl:9.2f} {pnl/len(r):7.3f}")
