"""Same CALIBRATED pair harness, on 15m markets.

Why 15m is the one duration worth another look: its aggregate maker terrain is
the best of the three measured (net +0.259 c/sh, vs 5m -0.010 and 1h -0.254),
and it gives 96 bars/day vs 24. The 1h version of this harness reproduces live
PnL to within 3% (-0.246 sim vs -0.238 live), so its verdicts are trustworthy.

⚠️ 15m archives live in <coin>-mrec15m/ but the FILES are named <coin>-mrec-*
(ledger #21) — a wrong glob is a silent zero. 15m DOES carry RES rows.
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB = 0.20 * 0.07
BAR = 900.0


class Cfg:
    def __init__(self, name, ceil=0.985, edge=0.015, size=10.0, batch=5.0,
                 delay=0.4, queue=True, mid_lo=0.12, mid_hi=0.88,
                 quit_tl=30.0, warmup=5.0, rand=False):
        self.__dict__.update(locals()); del self.self


class Bar:
    __slots__ = ('c', 'o', 'inv', 'cost', 'pend', 'fills', 'pairpnl')

    def __init__(self, cfg):
        self.c = cfg
        self.o = {'U': None, 'D': None}
        self.inv = {'U': 0.0, 'D': 0.0}
        self.cost = {'U': 0.0, 'D': 0.0}
        self.pend = []; self.fills = 0; self.pairpnl = 0.0

    def on_prints(self, prints):
        for _ts, ltok, mpx, sz in prints:
            o = self.o[ltok]
            if o is None or mpx > o['px'] + 1e-9:
                continue
            if self.c.queue and o['qa'] > 0:
                eat = min(o['qa'], sz); o['qa'] -= eat; sz -= eat
                if sz <= 1e-9:
                    continue
            got = min(o['rem'], sz)
            if got > 0:
                self.inv[ltok] += got; self.cost[ltok] += got * o['px']
                o['rem'] -= got; self.fills += 1
                if o['rem'] <= 1e-9:
                    self.o[ltok] = None

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das):
        c = self.c
        while self.pend and self.pend[0][0] <= t:
            self.pend.pop(0)[1]()
        if ub is None or ua is None or db is None or da is None:
            return
        mid = (ub + ua) / 2.0
        live = (c.quit_tl < tl and (BAR - tl) > c.warmup
                and c.mid_lo <= mid <= c.mid_hi)
        book = {'U': (ub, ubs or 0.0, mid), 'D': (db, dbs or 0.0, 1.0 - mid)}
        for tok in ('U', 'D'):
            bid, bsz, m = book[tok]
            other = 'D' if tok == 'U' else 'U'
            mine, theirs = self.inv[tok], self.inv[other]
            px = math.floor((m - c.edge) * 100 + 1e-9) / 100.0
            ok = live and mine < c.size - 1e-6 and (mine - theirs) < c.batch - 1e-6
            if ok and theirs > 1e-6 and c.ceil is not None:
                cap = math.floor((c.ceil - self.cost[other] / theirs) * 100 + 1e-9) / 100.0
                px = min(px, cap)
            if ok and px >= m - 0.004:
                ok = False
            if not ok or px < 0.01:
                if self.o[tok] is not None:
                    self.pend.append((t + c.delay, self._cancel(tok)))
                continue
            cur = self.o[tok]
            if cur is None:
                self.pend.append((t + c.delay, self._place(tok, px, bsz)))
            elif abs(cur['px'] - px) > 1e-9:
                self.pend.append((t + c.delay, self._place(tok, px, bsz, True)))

    def _cancel(self, tok):
        def f(): self.o[tok] = None
        return f

    def _place(self, tok, px, bsz, repl=False):
        def f():
            if self.o[tok] is not None and not repl:
                return
            rem = min(self.c.batch, self.c.size - self.inv[tok])
            if rem < 5:
                return
            self.o[tok] = dict(px=px, rem=rem, qa=(bsz if self.c.queue else 0.0))
        return f

    def settle(self, upwon):
        pnl = 0.0
        n0 = min(self.inv['U'], self.inv['D'])
        if n0 > 0:
            self.pairpnl = n0 * (1.0 - self.cost['U']/self.inv['U']
                                     - self.cost['D']/self.inv['D'])
        for tok in ('U', 'D'):
            if self.inv[tok] <= 0:
                continue
            won = upwon if tok == 'U' else 1 - upwon
            avg = self.cost[tok] / self.inv[tok]
            pnl += self.inv[tok] * ((won - avg) + REB * avg * (1 - avg))
        return pnl, n0, abs(self.inv['U'] - self.inv['D']), self.fills


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
    bars = {}
    acc = [dict(pnl=0.0, npair=0.0, nres=0.0, fills=0, bars=0, pp=0.0) for _ in cfgs]
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
                for s in st:
                    s.on_snap(d['t'], d['tl'], d['ub'], d['ubs'], d['ua'],
                              d['uas'], d['db'], d['dbs'], d['da'], d['das'])
    except Exception:
        return None
    for ws, st in bars.items():
        for i, s in enumerate(st):
            w = wins[ws]
            if s.c.rand:
                w = (ws // 900) % 2
            pnl, npair, nres, nf = s.settle(w)
            a = acc[i]; a['bars'] += 1
            a['pnl'] += pnl; a['npair'] += npair; a['nres'] += nres
            a['fills'] += nf; a['pp'] += s.pairpnl
    return acc


if __name__ == '__main__':
    coin = sys.argv[1] if len(sys.argv) > 1 else 'btc'
    files = sorted(glob.glob(os.path.join(MREC, coin + '-mrec15m',
                                          f'{coin}-mrec-*.jsonl.gz')))
    assert files, 'NO FILES (ledger #21: dir is -mrec15m but files are -mrec-*)'
    pool = Pool(10)
    wins = {}
    for w in pool.imap_unordered(res_scan, files, chunksize=4):
        wins.update(w)
    cfgs = []
    for e in (0.005, 0.010, 0.015):
        for c in (0.985, 1.00, None):
            cfgs.append(Cfg(f'e={e*100:.1f}c ceil={c if c else "OFF"}', edge=e, ceil=c))
    cfgs.append(Cfg('e=1.0c ceil=0.985 RAND', edge=0.010, ceil=0.985, rand=True))
    T = [dict(pnl=0.0, npair=0.0, nres=0.0, fills=0, bars=0, pp=0.0) for _ in cfgs]
    for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files], chunksize=2):
        if acc is None:
            continue
        for t, a in zip(T, acc):
            for k in t:
                t[k] += a[k]
    print(f'15m {coin}, {len(wins)} resolved bars, {len(files)} files')
    print(f"  {'config':22s} {'pairsh':>7s} {'ressh':>6s} {'res%':>5s} "
          f"{'pair$':>8s} {'resid$':>8s} {'PnL':>9s} {'$/bar':>7s}")
    for c, t in zip(cfgs, T):
        tot = t['npair'] * 2 + t['nres']
        if tot <= 0:
            print(f"  {c.name:22s} no fills"); continue
        print(f"  {c.name:22s} {t['npair']:7.0f} {t['nres']:6.0f} "
              f"{t['nres']/tot*100:4.0f}% {t['pp']:8.2f} {t['pnl']-t['pp']:8.2f} "
              f"{t['pnl']:9.2f} {t['pnl']/max(1,t['bars']):7.3f}")
