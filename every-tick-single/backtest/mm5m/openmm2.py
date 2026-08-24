"""OPENMM v2 - fixes + the defence the field's makers actually have.

v1 flaws fixed:
  1. price was computed from a 0.4s-stale book, so orders landed ABOVE the new
     bid right after a downtick = buying into a falling market.  Now the price
     is read from the book AT EXECUTION TIME and never placed above the touch.
  2. added a spot-velocity PULL: cancel the bid on a token when Binance spot is
     moving against it (we see spot at 100ms; this is what lets a maker dodge
     the pickoff that a pure book-follower eats).
  3. inventory skew: once one side fills, the other side is the completing leg.
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
from collections import defaultdict, deque
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB, FEE, TICK = 0.20 * 0.07, 0.07, 0.01


def decay_rate(tl):
    if tl > 290: return 0.307
    if tl > 240: return 0.377
    if tl > 120: return 0.548
    if tl > 60:  return 0.524
    if tl > 30:  return 0.524
    return 0.459


class Cfg:
    def __init__(self, name, tl_hi=297, tl_lo=240, offset=0, size=50.0, delay=0.4,
                 queue=True, max_fills=1, band=(0.30, 0.70), rand=False,
                 pull_bps=None, pull_win=2.0, skew=False, cancel_stale=True,
                 cancel_delay=None):
        self.__dict__.update(locals()); del self.self
        if self.cancel_delay is None:
            self.cancel_delay = self.delay


class BarSim:
    __slots__ = ('c', 'o', 'fills', 'pend', 'nf', 'bk', 'lead_h', 'decomp', 'nplace')

    def __init__(self, cfg):
        self.c = cfg
        self.o = {'U': None, 'D': None}
        self.fills = []
        self.pend = []
        self.nf = {'U': 0, 'D': 0}
        self.bk = None                 # latest book, read at execution time
        self.lead_h = deque(maxlen=60)
        self.nplace = 0

    def _decay(self, dt, tl):
        f = math.exp(-decay_rate(tl) * dt)
        for tok in ('U', 'D'):
            o = self.o[tok]
            if o is not None and o['at_touch']:
                o['qa'] *= f

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
                self.fills.append((ltok, o['px'], got, False))
                o['rem'] -= got
                if o['rem'] <= 1e-9:
                    self.o[ltok] = None
                    self.nf[ltok] += 1

    def _spot_move(self, t):
        """bps change in lead over the pull window (+ = spot rising = UP favoured)"""
        if not self.lead_h:
            return None
        t0 = t - self.c.pull_win
        old = None
        for ts, ld in self.lead_h:
            if ts <= t0:
                old = ld
            else:
                break
        if old is None:
            return None
        return self.lead_h[-1][1] - old

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        c = self.c
        self._decay(dt, tl)
        if lead is not None:
            self.lead_h.append((t, lead))
        if ub is not None and db is not None:
            self.bk = {'U': (ub, ubs or 0.0), 'D': (db, dbs or 0.0)}
        while self.pend and self.pend[0][0] <= t:
            self.pend.pop(0)[1]()
        if self.bk is None:
            return
        live = c.tl_lo <= tl <= c.tl_hi
        mv = self._spot_move(t) if c.pull_bps is not None else None
        for tok in ('U', 'D'):
            bid, _ = self.bk[tok]
            px_now = round(bid - c.offset * TICK, 2)
            want = live and c.band[0] <= px_now <= c.band[1] and self.nf[tok] < c.max_fills
            # spot moving AGAINST this token -> stand down
            if want and mv is not None:
                adverse = -mv if tok == 'U' else mv
                if adverse >= c.pull_bps:
                    want = False
            o = self.o[tok]
            if not want:
                if o is not None:
                    self.pend.append((t + c.delay, self._cancel(tok)))
                continue
            if o is None:
                self.pend.append((t + c.delay, self._place(tok)))
            elif c.cancel_stale and o['px'] > bid + 1e-9:
                self.pend.append((t + c.delay, self._cancel(tok)))
            else:
                o['at_touch'] = abs(o['px'] - bid) < 1e-9

    def _cancel(self, tok):
        def f(): self.o[tok] = None
        return f

    def _place(self, tok):
        c = self.c
        def f():
            if self.o[tok] is not None or self.nf[tok] >= c.max_fills or self.bk is None:
                return
            bid, bsz = self.bk[tok]                 # EXECUTION-TIME book
            px = round(bid - c.offset * TICK, 2)
            if not (c.band[0] <= px <= c.band[1]):
                return
            at_touch = c.offset == 0
            size = c.size
            if c.skew:                              # completing leg gets priority size
                other = 'D' if tok == 'U' else 'U'
                filled_other = sum(s for tk, _, s, _ in self.fills if tk == other)
                filled_me = sum(s for tk, _, s, _ in self.fills if tk == tok)
                need = filled_other - filled_me
                if need > 0:
                    size = min(c.size, need)
            self.o[tok] = dict(px=px, qa=(bsz if c.queue else 0.0),
                               rem=size, at_touch=at_touch)
        return f

    def settle(self, upwon):
        pos = defaultdict(list)
        for tok, px, sz, tk in self.fills:
            pos[tok].append((px, sz, tk))
        pnl = shares = 0.0
        for tok in ('U', 'D'):
            won = upwon if tok == 'U' else 1 - upwon
            for px, sz, tk in pos[tok]:
                pnl += sz * ((won - px) + REB * px * (1 - px))
                shares += sz
        nU = sum(s for _, s, _ in pos['U']); nD = sum(s for _, s, _ in pos['D'])
        # decomposition: matched pairs pay a certain $1 for (pxU+pxD); the
        # leftover leg is the directional residual
        paired = min(nU, nD)
        pnl_pair = pnl_res = 0.0
        if paired > 0:
            au = sum(px * s for px, s, _ in pos['U']) / nU if nU else 0.0
            ad = sum(px * s for px, s, _ in pos['D']) / nD if nD else 0.0
            pnl_pair = paired * ((1.0 - au - ad)
                                 + REB * au * (1 - au) + REB * ad * (1 - ad))
        pnl_res = pnl - pnl_pair
        self.decomp = (pnl_pair, pnl_res, paired, abs(nU - nD))
        return pnl, shares, len(self.fills), paired, abs(nU - nD)


def res_scan(path):
    out = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    d = json.loads(line)
                    out[d['ws']] = 1 if d['win'] == 'UP' else 0
    except Exception:
        pass
    return out


def run_file(args):
    path, wins, cfgs = args
    day = os.path.basename(path).split('-')[2]
    bars = {}; last_t = {}
    acc = [dict(pnl=0.0, sh=0.0, fills=0, paired=0.0, resid=0.0, bars=0,
                px=0.0, pp=0.0, pr=0.0, npl=0, day=defaultdict(float),
                dayp=defaultdict(float), dayr=defaultdict(float),
                daysh=defaultdict(float)) for _ in cfgs]
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"cur"' not in line:
                    continue
                d = json.loads(line)
                ws = d['ws']
                if ws not in wins:
                    continue
                st = bars.get(ws)
                if st is None:
                    st = bars[ws] = [BarSim(c) for c in cfgs]
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
                t = d['t']
                dt = min(1.0, max(0.0, t - last_t.get(ws, t)))
                last_t[ws] = t
                for s in st:
                    s.on_snap(t, d['tl'], d['ub'], d['ubs'], d['ua'], d['uas'],
                              d['db'], d['dbs'], d['da'], d['das'], d['lead_bps'], dt)
    except (EOFError, OSError, gzip.BadGzipFile):
        return None
    for ws, st in bars.items():
        for i, s in enumerate(st):
            w = wins[ws]
            if s.c.rand:
                w = (ws // 300) % 2
            pnl, sh, nf, pr_, rs = s.settle(w)
            a = acc[i]; a['bars'] += 1
            if nf:
                a['pnl'] += pnl; a['sh'] += sh; a['fills'] += nf
                a['paired'] += pr_; a['resid'] += rs; a['day'][day] += pnl
                a['px'] += sum(px * sz for _, px, sz, _ in s.fills)
                a['pp'] += s.decomp[0]; a['pr'] += s.decomp[1]
                a['npl'] += s.nplace
                a['dayp'][day] += s.decomp[0]; a['dayr'][day] += s.decomp[1]
                a['daysh'][day] += sh
    return acc


def main(coins, cfgs, quiet=False):
    pool = Pool(10)
    T = {c.name: dict(pnl=0.0, sh=0.0, fills=0, paired=0.0, resid=0.0, bars=0,
                      px=0.0, pp=0.0, pr=0.0, npl=0, day=defaultdict(float)) for c in cfgs}
    for coin in coins:
        files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
        wins = {}
        for p in pool.imap_unordered(res_scan, files, chunksize=4):
            wins.update(p)
        for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files], chunksize=2):
            if acc is None: continue
            for c, a in zip(cfgs, acc):
                t = T[c.name]
                for k in ('pnl', 'sh', 'fills', 'paired', 'resid', 'bars', 'px', 'pp', 'pr', 'npl'):
                    t[k] += a[k]
                for k, v in a['day'].items(): t['day'][k] += v
                for k, v in a.get('dayp', {}).items(): t.setdefault('dayp', defaultdict(float))[k] += v
                for k, v in a.get('dayr', {}).items(): t.setdefault('dayr', defaultdict(float))[k] += v
                for k, v in a.get('daysh', {}).items(): t.setdefault('daysh', defaultdict(float))[k] += v
    print(f"  {'config':22s} {'fills':>7s} {'shares':>8s} {'avgpx':>6s} {'c/sh':>7s} "
          f"{'$total':>9s} {'$/day':>8s} {'t':>6s} {'pair%':>6s}")
    for c in cfgs:
        t = T[c.name]
        if not t['fills']:
            print(f"  {c.name:22s} NO FILLS"); continue
        dp = np.array(list(t['day'].values())); nd = len(dp)
        ts_ = dp.mean() / (dp.std(ddof=1) / math.sqrt(nd)) if nd > 1 else float('nan')
        print(f"  {c.name:22s} {t['fills']:7d} {t['sh']:8.0f} {t['px']/t['sh']:6.3f} "
              f"{t['pnl']/t['sh']*100:+7.3f} {t['pnl']:9.2f} {t['pnl']/nd:8.2f} "
              f"{ts_:+6.2f} {2*t['paired']/t['sh']*100:6.1f}"
              f"   pair$ {t['pp']:+8.1f}  resid$ {t['pr']:+8.1f}"
              f"  pl/bar {t['npl']/max(1,t['bars']):5.1f}")
    if os.environ.get('DUMPDAYS'):
        import json as _j
        _j.dump({k: dict(day=dict(v['day']), pair=dict(v.get('dayp', {})),
                         resid=dict(v.get('dayr', {})), sh=dict(v.get('daysh', {})))
                 for k, v in T.items()},
                open(os.environ['DUMPDAYS'], 'w'))
    return T


if __name__ == '__main__':
    coins = sys.argv[1].split(',') if len(sys.argv) > 1 else ['btc']
    cfgs = [
        Cfg('v1-style (stale px)', cancel_stale=True),
        Cfg('v2 exec-time px',     cancel_stale=True),
        Cfg('v2 + pull 1.0bps',    pull_bps=1.0),
        Cfg('v2 + pull 0.5bps',    pull_bps=0.5),
        Cfg('v2 + pull 0.25bps',   pull_bps=0.25),
        Cfg('v2 pull.5 + skew',    pull_bps=0.5, skew=True),
        Cfg('v2 pull.5 behind1',   pull_bps=0.5, offset=1),
        Cfg('RAND(control)',       pull_bps=0.5, rand=True),
        Cfg('NOQ(control)',        pull_bps=0.5, queue=False),
    ]
    main(coins, cfgs)
