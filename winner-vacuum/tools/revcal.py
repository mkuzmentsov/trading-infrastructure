r"""revcal — is the PM 5m book CALIBRATED, and can "buy the dip for the occasional
reversion" ever be traded? (2026-08-23, §42)

Why this is the definitive test: it uses NO estimator. The book prices are what
the venue showed, and RES is the venue's own settlement label, so
"what did the losing side cost, and how often did it win" is answered with
zero recon error, zero proxy, and no fill model at all (the fill model only
matters if the answer is positive — it is not).

Coverage: local archive `every-tick-single/data/mrec/<coin>/`,
2026-07-30 -> 08-17, 7 coins, 28,422 bars, 376,002 (bar x time) observations
on a 20-point tl grid from T-270s to T-3s.

  python3 revcal.py extract <workdir>      # -> <workdir>/rev_<coin>.pkl
  python3 revcal.py calib   <workdir>      # dog + favourite calibration by tl
  python3 revcal.py dip     <workdir>      # buy the dog that JUST got crushed
  python3 revcal.py violence <workdir>     # buy the dog after a violent move
  python3 revcal.py scalp   <workdir>      # sell into a retrace instead of holding
  python3 revcal.py coins   <workdir>      # per-coin / per-day / vig / maker-side

⚠️ raw rows are COMPACT json — `"role":"cur"`, no spaces (ledger #1).
"""
import gzip, json, glob, os, pickle, sys, math, bisect, collections
import datetime as dt, statistics as st

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', '..', 'every-tick-single', 'data', 'mrec')
COINS = ['btc', 'eth', 'sol', 'xrp', 'bnb', 'doge', 'hype']
GRID = [3, 5, 7, 10, 13, 16, 20, 25, 30, 40, 50, 60, 75, 90, 120, 150, 180, 210, 240, 270]
PAIRS = [(20, 50), (30, 60), (60, 120), (90, 150), (120, 180), (180, 240)]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / 2 / n) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / 4 / n / n) / d
    return (100 * (c - h), 100 * (c + h))


def extract(W):
    for coin in COINS:
        out = f'{W}/rev_{coin}.pkl'
        if os.path.exists(out):
            print('skip', coin, flush=True); continue
        res, bars = {}, collections.defaultdict(dict)
        for f in sorted(glob.glob(f'{SRC}/{coin}/*.jsonl.gz')):
            with gzip.open(f, 'rt') as fh:
                for l in fh:
                    if '"RES"' in l:
                        d = json.loads(l); res[d['ws']] = d['win']; continue
                    if '"role":"cur"' not in l:
                        continue
                    d = json.loads(l)
                    tl = d.get('tl')
                    if tl is None or tl < 2 or tl > 295:
                        continue
                    i = bisect.bisect_right(GRID, tl) - 1
                    if i < 0:
                        continue
                    g = GRID[i]; b = bars[d['ws']]; prev = b.get(g)
                    if prev is None or tl < prev[0]:
                        b[g] = (round(tl, 2), d.get('ub'), d.get('ubs'), d.get('ua'),
                                d.get('uas'), d.get('db'), d.get('dbs'), d.get('da'),
                                d.get('das'), d.get('spot'), d.get('lead_bps'), d.get('volsh'))
        keep = {ws: v for ws, v in bars.items() if ws in res}
        pickle.dump(dict(res=res, bars=keep), open(out, 'wb'), 2)
        print(coin, 'bars', len(keep), flush=True)


def load(W):
    """-> list of per (bar, grid-point) observations, dog side resolved by mid."""
    OBS, VIG = [], collections.defaultdict(list)
    for f in sorted(glob.glob(f'{W}/rev_*.pkl')):
        coin = f.split('rev_')[-1][:-4]
        D = pickle.load(open(f, 'rb')); res = D['res']
        for ws, b in D['bars'].items():
            win = res.get(ws)
            if not win:
                continue
            day = dt.datetime.fromtimestamp(ws, dt.timezone.utc).strftime('%m-%d')
            for g, v in b.items():
                tl, ub, ubs, ua, uas, db, dbs, da, das, spot, lead, volsh = v
                if None in (ub, db, ua, da):
                    continue
                VIG[(coin, g)].append(ua + da - 1.0)
                umid = (ub + ua) / 2; dmid = (db + da) / 2
                if abs(umid - dmid) < 1e-9:
                    continue
                dog = 'DOWN' if umid > dmid else 'UP'
                OBS.append(dict(coin=coin, ws=ws, day=day, g=g, dog=dog,
                                dask=(da if dog == 'DOWN' else ua),
                                dbid=(db if dog == 'DOWN' else ub),
                                dsz=(das if dog == 'DOWN' else uas) or 0,
                                fask=(ua if dog == 'DOWN' else da),
                                fsz=(uas if dog == 'DOWN' else das) or 0,
                                dwin=(win == dog), spot=spot))
    return OBS, VIG


def _row(tag, sub, price='dask', winkey='dwin', minn=100):
    if len(sub) < minn:
        return
    n = len(sub); w = sum(1 for o in sub if o[winkey]); a = sum(o[price] for o in sub) / n
    ci = wilson(w, n)
    print('  %-26s n=%6d  px=%.4f  win=%5.2f%% [%5.2f,%5.2f]  EV=%+.4f  %+7.1f%%'
          % (tag, n, a, 100 * w / n, ci[0], ci[1], w / n - a, 100 * (w / n - a) / a))


def calib(W):
    OBS, _ = load(W)
    print('observations %d  bars %d' % (len(OBS), len({(o['coin'], o['ws']) for o in OBS})))
    print('\n== THE DOG at its ask, hold to redemption ==')
    for g in GRID:
        for lo, hi in [(0, .02), (.02, .05), (.05, .10), (.10, .20), (.20, .30), (.30, .40), (.40, .50)]:
            _row('tl=%-4d %.2f-%.2f' % (g, lo, hi),
                 [o for o in OBS if o['g'] == g and lo < o['dask'] <= hi and o['dsz'] >= 5], minn=30)
    print('\n== THE FAVOURITE at its ask (the mirror) ==')
    for o in OBS:
        o['fwin'] = not o['dwin']
    for g in (20, 30, 60, 90, 120, 180, 240, 270):
        for lo, hi in [(.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, .95), (.95, .98), (.98, 1.0)]:
            _row('tl=%-4d %.2f-%.2f' % (g, lo, hi),
                 [o for o in OBS if o['g'] == g and lo < o['fask'] <= hi and o['fsz'] >= 5],
                 price='fask', winkey='fwin')


def dip(W):
    """buy the dog that JUST got crushed — the literal 'buy the dip'."""
    OBS, _ = load(W)
    IDX = {(o['coin'], o['ws'], o['g']): o for o in OBS}
    for now, then in PAIRS:
        print('\n== dip at tl=%d, measured against tl=%d ==' % (now, then))
        cells = collections.defaultdict(list)
        for o in OBS:
            if o['g'] != now or o['dsz'] < 5 or o['dask'] > 0.5:
                continue
            p = IDX.get((o['coin'], o['ws'], then))
            if not p or p['dog'] != o['dog']:
                continue
            drop = p['dask'] - o['dask']
            pb = '%.2f' % (0.05 * round(o['dask'] / 0.05))
            for lo, hi in [(0, .02), (.02, .05), (.05, .10), (.10, .20), (.20, 1.0)]:
                if lo < drop <= hi:
                    cells[(pb, '%.2f-%.2f' % (lo, hi))].append(o); break
        for k in sorted(cells):
            _row('p~%s fell %s' % k, cells[k], minn=150)


def violence(W):
    """buy the dog right after the UNDERLYING moved violently against it."""
    OBS, _ = load(W)
    IDX = {(o['coin'], o['ws'], o['g']): o for o in OBS}
    for now, then in PAIRS:
        per = collections.defaultdict(list)
        for o in OBS:
            if o['g'] != now:
                continue
            p = IDX.get((o['coin'], o['ws'], then))
            if p and o['spot'] and p['spot']:
                per[o['coin']].append(abs((o['spot'] - p['spot']) / p['spot'] * 1e4))
        scale = {c: st.median(v) for c, v in per.items() if len(v) > 200}
        print('\n== violence at tl=%d over the previous %ds ==' % (now, then - now))
        cells = collections.defaultdict(list)
        for o in OBS:
            if o['g'] != now or o['dsz'] < 5 or o['dask'] > 0.5 or o['coin'] not in scale:
                continue
            p = IDX.get((o['coin'], o['ws'], then))
            if not p or not o['spot'] or not p['spot']:
                continue
            mv = (o['spot'] - p['spot']) / p['spot'] * 1e4
            if not ((mv > 0) if o['dog'] == 'DOWN' else (mv < 0)):
                continue                      # the move must be AGAINST the dog
            z = abs(mv) / scale[o['coin']]
            vb = '<1x' if z < 1 else '1-2x' if z < 2 else '2-3x' if z < 3 else '3-5x' if z < 5 else '>5x'
            cells[(vb, '%.2f' % (0.05 * round(o['dask'] / 0.05)))].append(o)
        for k in sorted(cells):
            _row('%s move, p~%s' % k, cells[k], minn=150)


def scalp(W):
    """never hold: sell the dog into the first retrace of +X."""
    OBS, _ = load(W)
    BY = collections.defaultdict(dict)
    for o in OBS:
        BY[(o['coin'], o['ws'])][o['g']] = o
    print('== buy the dog at the ask, exit at the first later bid >= entry+X, else ride to RES ==')
    for entry in (150, 120, 90, 60):
        for X in (0.03, 0.05, 0.10):
            n = hit = 0; pnl = stake = 0.0
            for r in BY.values():
                a = r.get(entry)
                if not a or a['dsz'] < 5 or not (0.05 < a['dask'] <= 0.35):
                    continue
                n += 1; stake += a['dask']; done = False
                for g in [g for g in GRID if g < entry]:
                    q = r.get(g)
                    if q and q['dog'] == a['dog'] and q['dbid'] >= a['dask'] + X:
                        pnl += q['dbid'] - a['dask']; hit += 1; done = True; break
                if not done:
                    pnl += (1.0 if a['dwin'] else 0.0) - a['dask']
            if n:
                print('  entry tl=%3d target +%.2f: n=%5d scalped %5.1f%%  ROI %+6.2f%%'
                      % (entry, X, n, 100 * hit / n, 100 * pnl / stake))


def coins(W):
    OBS, VIG = load(W)
    print('== the vig (ua+da-1), median by coin x tl ==')
    print('   coin  ' + ''.join('%8d' % g for g in (10, 20, 30, 60, 90, 120, 180, 240)))
    for c in sorted({o['coin'] for o in OBS}):
        print('  %-6s' % c + ''.join('%8.3f' % (st.median(VIG[(c, g)]) if VIG.get((c, g)) else float('nan'))
                                     for g in (10, 20, 30, 60, 90, 120, 180, 240)))
    cell = [o for o in OBS if 30 <= o['g'] <= 180 and 0.05 < o['dask'] <= 0.35 and o['dsz'] >= 5]
    print('\n== the dog at 0.05-0.35, tl 30-180 ==')
    _row('POOLED', cell)
    for c in sorted({o['coin'] for o in cell}):
        _row('coin=%s' % c, [o for o in cell if o['coin'] == c])
    for d in sorted({o['day'] for o in cell}):
        _row('day=%s' % d, [o for o in cell if o['day'] == d])
    n = len(cell); w = sum(o['dwin'] for o in cell)
    print('\n  fair %.4f | mean ASK %.4f (%+.1f%% vs fair) | mean BID %.4f (%+.1f%%)'
          % (w / n, sum(o['dask'] for o in cell) / n,
             100 * (sum(o['dask'] for o in cell) / n - w / n) / (w / n),
             sum(o['dbid'] for o in cell) / n,
             100 * (sum(o['dbid'] for o in cell) / n - w / n) / (w / n)))
    print('  => even a PERFECT maker fill at the dog bid earns only %+.1f%% gross,'
          % (100 * (w / n - sum(o['dbid'] for o in cell) / n) / (sum(o['dbid'] for o in cell) / n)))
    print('     which the measured -0.47c/fill resting adverse selection erases (maker-program-2026-08).')


if __name__ == '__main__':
    dict(extract=extract, calib=calib, dip=dip, violence=violence,
         scalp=scalp, coins=coins)[sys.argv[1]](sys.argv[2])
