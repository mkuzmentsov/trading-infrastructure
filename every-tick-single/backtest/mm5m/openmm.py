"""OPENMM - two-sided maker quoting in the .40-.60 zone, first N seconds of the bar.

Fill model (calibrated, not guessed):
  queue ahead decays exponentially at the rate MEASURED in queuedyn.py
  (cancellations dominate trades 2-4x; half-life 1.3-2.3s by tl bucket),
  ONLY while our level is the touch; no decay when the market has moved away.
  Trades at or through our level consume queue-ahead first, then us (FIFO).
  Reaction delay on every place/cancel.  Hold to resolution unless a taker
  completion is enabled (locks a pair only if the two legs sum <= PAIR_CEIL).

Controls that must behave or the model is broken:
  NOQ    - ignore the queue     -> must be BETTER than the calibrated run
  FULL   - quote the whole bar  -> must be WORSE (terrain says mid-bar is toxic)
  RAND   - outcomes shuffled    -> must land near -(taker fee share), i.e. ~ -0 gross
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB = 0.20 * 0.07
FEE = 0.07
TICK = 0.01

# measured net cancellation rate (fraction of standing size per second), by tl
def decay_rate(tl):
    if tl > 290: return 0.307
    if tl > 240: return 0.377
    if tl > 120: return 0.548
    if tl > 60:  return 0.524
    if tl > 30:  return 0.524
    return 0.459


class Cfg:
    def __init__(self, name, tl_hi=297, tl_lo=240, offset=0, size=50.0, delay=0.4,
                 queue=True, max_fills=1, pair_ceil=0.985, taker_complete=False,
                 lead_max=99.0, band=(0.30, 0.70), rand=False, requote=True):
        self.__dict__.update(locals()); del self.self


class BarSim:
    __slots__ = ('c', 'o', 'fills', 'pend', 'nf')

    def __init__(self, cfg):
        self.c = cfg
        self.o = {'U': None, 'D': None}     # dict(px, qa, rem, at_touch)
        self.fills = []                     # (tok, px, sz, taker)
        self.pend = []
        self.nf = {'U': 0, 'D': 0}

    def _decay(self, dt, tl):
        r = decay_rate(tl)
        f = math.exp(-r * dt)
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

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        c = self.c
        self._decay(dt, tl)
        while self.pend and self.pend[0][0] <= t:
            self.pend.pop(0)[1]()
        if ub is None or ua is None or db is None or da is None:
            return
        live = c.tl_lo <= tl <= c.tl_hi and (lead is None or abs(lead) <= c.lead_max)
        book = {'U': (ub, ubs or 0.0), 'D': (db, dbs or 0.0)}
        for tok in ('U', 'D'):
            bid, bsz = book[tok]
            px = round(bid - c.offset * TICK, 2)
            want = live and c.band[0] <= px <= c.band[1] and self.nf[tok] < c.max_fills
            o = self.o[tok]
            if not want:
                if o is not None:
                    self.pend.append((t + c.delay, self._cancel(tok)))
                continue
            if o is None:
                if c.requote or self.nf[tok] == 0:
                    self.pend.append((t + c.delay, self._place(tok, px, bsz, c.offset == 0)))
            else:
                o['at_touch'] = abs(o['px'] - bid) < 1e-9
                if o['px'] > bid + 1e-9:        # market left us stranded ABOVE the bid
                    self.pend.append((t + c.delay, self._cancel(tok)))

    def _cancel(self, tok):
        def f(): self.o[tok] = None
        return f

    def _place(self, tok, px, bsz, at_touch):
        def f():
            if self.o[tok] is None and self.nf[tok] < self.c.max_fills:
                self.o[tok] = dict(px=px, qa=(bsz if self.c.queue else 0.0),
                                   rem=self.c.size, at_touch=at_touch)
        return f

    def settle(self, upwon):
        c = self.c
        pos = {'U': [], 'D': []}
        for tok, px, sz, tk in self.fills:
            pos[tok].append((px, sz, tk))
        pnl = shares = notional = 0.0
        for tok in ('U', 'D'):
            won = upwon if tok == 'U' else 1 - upwon
            for px, sz, tk in pos[tok]:
                pnl += sz * ((won - px) + (0.0 if tk else REB * px * (1 - px))
                             - (FEE * px * (1 - px) if tk else 0.0))
                shares += sz; notional += sz * px
        nU = sum(s for _, s, _ in pos['U']); nD = sum(s for _, s, _ in pos['D'])
        paired = min(nU, nD)
        return pnl, shares, notional, len(self.fills), paired, abs(nU - nD)


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
    acc = [dict(pnl=0.0, sh=0.0, no=0.0, fills=0, paired=0.0, resid=0.0,
                bars=0, day=defaultdict(float)) for _ in cfgs]
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
                w = (ws // 300) % 2                 # deterministic pseudo-outcome
            pnl, sh, no, nf, pr_, rs = s.settle(w)
            a = acc[i]; a['bars'] += 1
            if nf:
                a['pnl'] += pnl; a['sh'] += sh; a['no'] += no; a['fills'] += nf
                a['paired'] += pr_; a['resid'] += rs; a['day'][day] += pnl
    return acc


def main(coins, cfgs):
    pool = Pool(10)
    T = {c.name: dict(pnl=0.0, sh=0.0, no=0.0, fills=0, paired=0.0, resid=0.0,
                      bars=0, day=defaultdict(float)) for c in cfgs}
    for coin in coins:
        files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
        wins = {}
        for p in pool.imap_unordered(res_scan, files, chunksize=4):
            wins.update(p)
        per = {c.name: dict(pnl=0.0, sh=0.0, fills=0) for c in cfgs}
        for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files], chunksize=2):
            if acc is None: continue
            for c, a in zip(cfgs, acc):
                t = T[c.name]
                for k in ('pnl', 'sh', 'no', 'fills', 'paired', 'resid', 'bars'):
                    t[k] += a[k]
                for k, v in a['day'].items(): t['day'][k] += v
                for k in ('pnl', 'sh', 'fills'): per[c.name][k] += a[k]
        print(f'--- {coin} ---')
        for c in cfgs:
            p = per[c.name]
            if p['fills']:
                print(f"  {c.name:20s} fills {p['fills']:6d} sh {p['sh']:8.0f} "
                      f"${p['pnl']:8.2f}  {p['pnl']/p['sh']*100:+.3f} c/sh")
        sys.stdout.flush()
    print('\n===== TOTAL =====')
    print(f"  {'config':20s} {'fills':>7s} {'shares':>9s} {'c/sh':>7s} {'$total':>9s} "
          f"{'$/day':>8s} {'t':>6s} {'pair%':>6s} {'fills/bar':>9s}")
    for c in cfgs:
        t = T[c.name]
        if not t['fills']:
            print(f"  {c.name:20s} NO FILLS"); continue
        dp = np.array(list(t['day'].values())); nd = len(dp)
        tstat = dp.mean() / (dp.std(ddof=1) / math.sqrt(nd)) if nd > 1 else float('nan')
        print(f"  {c.name:20s} {t['fills']:7d} {t['sh']:9.0f} {t['pnl']/t['sh']*100:+7.3f} "
              f"{t['pnl']:9.2f} {t['pnl']/nd:8.2f} {tstat:+6.2f} "
              f"{2*t['paired']/t['sh']*100:6.1f} {t['fills']/max(1,t['bars']):9.3f}")
    return T


if __name__ == '__main__':
    coins = sys.argv[1].split(',') if len(sys.argv) > 1 else ['btc']
    cfgs = [
        Cfg('open60 touch',    tl_hi=297, tl_lo=240, offset=0),
        Cfg('open60 behind1',  tl_hi=297, tl_lo=240, offset=1),
        Cfg('open90 touch',    tl_hi=297, tl_lo=210, offset=0),
        Cfg('open30 touch',    tl_hi=297, tl_lo=270, offset=0),
        Cfg('NOQ(control)',    tl_hi=297, tl_lo=240, offset=0, queue=False),
        Cfg('FULL(control)',   tl_hi=297, tl_lo=45,  offset=0),
        Cfg('RAND(control)',   tl_hi=297, tl_lo=240, offset=0, rand=True),
    ]
    main(coins, cfgs)
