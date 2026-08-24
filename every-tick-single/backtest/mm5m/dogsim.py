"""Queue-aware sim of the 15m UNDERDOG maker: rest a BID on the cheap side at
.15-.30 and hold to resolution.

This is the gate that killed two field-data cells already (5m tail pool:
+0.9 c/sh field-wide -> -0.41 with a queue; 'swept-deep': +3.44 -> -4.2).
Field says at-touch +2.088 c/sh net. Does it survive a real queue?

Fill model identical to the 5m work: queue ahead = full displayed size at join,
decaying at the measured rate while we are the touch, FIFO consumption, prints
through our level sweep us, reaction delay on every action, hold to resolution.
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB, TICK = 0.20 * 0.07, 0.01
BAR = 900.0


def decay_rate(tl):            # measured on 5m; 15m books are calmer -> use the
    return 0.45                # mid of the observed 0.31-0.55 range


class Cfg:
    def __init__(self, name, lo=.15, hi=.30, size=5.0, delay=0.2, queue=True,
                 max_fills=1, tl_lo=0.0, tl_hi=900.0, rand=False, qmult=1.0):
        self.__dict__.update(locals()); del self.self


class Bar:
    __slots__ = ('c', 'o', 'fills', 'pend', 'nf', 'bk', 'nplace')

    def __init__(self, cfg):
        self.c = cfg; self.o = None; self.fills = []; self.pend = []
        self.nf = 0; self.bk = None; self.nplace = 0

    def on_prints(self, prints):
        o = self.o
        if o is None:
            return
        for _ts, ltok, mpx, sz in prints:
            if o is None or ltok != o['tok'] or mpx > o['px'] + 1e-9:
                continue
            if self.c.queue and o['qa'] > 0:
                eat = min(o['qa'], sz); o['qa'] -= eat; sz -= eat
                if sz <= 1e-9:
                    continue
            got = min(o['rem'], sz)
            if got > 0:
                self.fills.append((o['tok'], o['px'], got))
                o['rem'] -= got
                if o['rem'] <= 1e-9:
                    self.o = None; o = None; self.nf += 1

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, dt):
        c = self.c
        if self.o is not None and self.o['at_touch']:
            self.o['qa'] *= math.exp(-decay_rate(tl) * dt)
        while self.pend and self.pend[0][0] <= t:
            self.pend.pop(0)[1]()
        if ub is None or ua is None or db is None or da is None:
            return
        self.bk = {'U': (ub, ubs or 0.0), 'D': (db, dbs or 0.0)}
        # the UNDERDOG is whichever token trades lower
        tok = 'U' if (ub + ua) / 2.0 < 0.5 else 'D'
        bid, bsz = self.bk[tok]
        px = round(bid, 2)
        want = (c.tl_lo <= tl <= c.tl_hi and c.lo - 1e-9 <= px <= c.hi + 1e-9
                and self.nf < c.max_fills)
        o = self.o
        if not want:
            if o is not None:
                self.pend.append((t + c.delay, self._cancel))
            return
        if o is None:
            self.pend.append((t + c.delay, self._place(tok, px, bsz)))
        elif o['tok'] != tok or abs(o['px'] - px) > 1e-9:
            self.pend.append((t + c.delay, self._place(tok, px, bsz, True)))
        else:
            o['at_touch'] = True

    def _cancel(self):
        self.o = None

    def _place(self, tok, px, bsz, replace=False):
        def f():
            if (self.o is not None and not replace) or self.nf >= self.c.max_fills:
                return
            self.o = dict(tok=tok, px=px, rem=self.c.size, at_touch=True,
                          qa=(bsz * self.c.qmult if self.c.queue else 0.0))
            self.nplace += 1
        return f

    def settle(self, upwon):
        pnl = sh = 0.0
        for tok, px, s in self.fills:
            won = upwon if tok == 'U' else 1 - upwon
            pnl += s * ((won - px) + REB * px * (1 - px)); sh += s
        return pnl, sh, len(self.fills)


def res_scan(path):
    out = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    d = json.loads(line); out[d['ws']] = 1 if d['win'] == 'UP' else 0
    except Exception:
        pass
    return out


def run_file(args):
    path, wins, cfgs = args
    day = os.path.basename(path).split('-')[2]
    bars = {}; last = {}
    acc = [dict(pnl=0.0, sh=0.0, fills=0, bars=0, npl=0, px=0.0,
                day=defaultdict(float)) for _ in cfgs]
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line); ws = d['ws']
                if ws not in wins:
                    continue
                st = bars.get(ws)
                if st is None:
                    st = bars[ws] = [Bar(c) for c in cfgs]
                trd = d.get('trd')
                if trd:
                    pr = []
                    for ts, tok, px, sz, side in trd:
                        upx = px if tok == 'U' else 1.0 - px
                        tbu = (side == 'BUY') == (tok == 'U')
                        pr.append((ts, 'D' if tbu else 'U',
                                   round((1 - upx) if tbu else upx, 2), sz))
                    pr.sort()
                    for s in st:
                        s.on_prints(pr)
                t = d['t']; dt = min(1.0, max(0.0, t - last.get(ws, t))); last[ws] = t
                for s in st:
                    s.on_snap(t, d['tl'], d['ub'], d['ubs'], d['ua'], d['uas'],
                              d['db'], d['dbs'], d['da'], d['das'], dt)
    except Exception:
        return None
    for ws, st in bars.items():
        for i, s in enumerate(st):
            w = wins[ws]
            if s.c.rand:
                w = (ws // 900) % 2
            pnl, sh, nf = s.settle(w)
            a = acc[i]; a['bars'] += 1; a['npl'] += s.nplace
            if nf:
                a['pnl'] += pnl; a['sh'] += sh; a['fills'] += nf
                a['day'][day] += pnl
                a['px'] += sum(px * s2 for _, px, s2 in s.fills)
    return acc


def main(coins, cfgs):
    pool = Pool(10)
    T = {c.name: dict(pnl=0.0, sh=0.0, fills=0, bars=0, npl=0, px=0.0,
                      day=defaultdict(float)) for c in cfgs}
    for coin in coins:
        files = sorted(glob.glob(os.path.join(MREC, coin + '-mrec15m',
                                              f'{coin}-mrec-*.jsonl.gz')))
        assert files, f'NO FILES for {coin} (ledger #21: check dir/prefix)'
        wins = {}
        for p in pool.imap_unordered(res_scan, files, chunksize=4):
            wins.update(p)
        for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files],
                                       chunksize=2):
            if acc is None: continue
            for c, a in zip(cfgs, acc):
                t = T[c.name]
                for k in ('pnl', 'sh', 'fills', 'bars', 'npl', 'px'):
                    t[k] += a[k]
                for k, v in a['day'].items(): t['day'][k] += v
    print(f"  {'config':26s} {'fills':>6s} {'shares':>8s} {'avgpx':>6s} {'c/sh':>7s} "
          f"{'$total':>8s} {'$/day':>7s} {'t':>6s} {'pl/bar':>6s}")
    for c in cfgs:
        t = T[c.name]
        if not t['fills']:
            print(f"  {c.name:26s} NO FILLS"); continue
        dp = np.array(list(t['day'].values())); nd = len(dp)
        ts_ = dp.mean()/(dp.std(ddof=1)/math.sqrt(nd)) if nd > 1 else float('nan')
        print(f"  {c.name:26s} {t['fills']:6d} {t['sh']:8.0f} {t['px']/t['sh']:6.3f} "
              f"{t['pnl']/t['sh']*100:+7.3f} {t['pnl']:8.2f} {t['pnl']/nd:7.2f} "
              f"{ts_:+6.2f} {t['npl']/max(1,t['bars']):6.1f}")


if __name__ == '__main__':
    cfgs = [
        Cfg('dog .15-.30 all-bar'),
        Cfg('dog .15-.30 RAND', rand=True),
        Cfg('dog .15-.30 NOQ', queue=False),
        Cfg('dog .15-.30 late', tl_hi=450),
        Cfg('dog .10-.35 all-bar', lo=.10, hi=.35),
        Cfg('dog .20-.30 all-bar', lo=.20, hi=.30),
    ]
    main(sys.argv[1].split(','), cfgs)
