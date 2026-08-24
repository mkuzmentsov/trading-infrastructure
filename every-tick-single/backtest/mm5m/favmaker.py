"""FAVMAKER: queue-aware simulation of resting a BUY on the FAVOURITE at .88-.96.

Mechanic (why it dodges the ONE WALL): the informed taker flow lifts the eventual
WINNER.  We rest on the favourite, so the informed taker is on OUR side; our
counterparties are the dog-lottery buyer and the impatient profit-taker.

Fill model (deliberately pessimistic):
  - join the touch  -> queue ahead = the ENTIRE displayed size at that level
  - queue only shrinks via observed prints (cancellations invisible => conservative)
  - a print strictly below our price implies our level was swept => consume us too
  - reaction delay applied to every place/cancel decision
  - hold to resolution, no exits
Controls: NOQ (queue ignored) must be BETTER than the queue-aware run, and the
unconditional MID config must lose (both catch fill-model bugs).
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB = 0.20 * 0.07
TICK = 0.01


class Cfg:
    def __init__(self, name, lo=.90, hi=.96, tl_lo=60, tl_hi=250, lead_min=4.0,
                 size=50.0, improve=False, queue=True, chase=True, delay=0.4,
                 max_fills=1, mode='fav', flat_ok=False):
        self.__dict__.update(locals()); del self.self


class BarSim:
    """One bar, one config."""
    __slots__ = ('c', 'order', 'fills', 'pend', 'nfill')

    def __init__(self, cfg):
        self.c = cfg
        self.order = None      # dict(tok, px, qa, rem)
        self.fills = []        # (tok, px, sz)
        self.pend = []         # (t_effective, action)
        self.nfill = 0

    # ---- fills from prints -------------------------------------------------
    def on_prints(self, prints):
        o = self.order
        if o is None:
            return
        for _ts, ltok, mpx, sz in prints:      # ltok = token the MAKER ends up long
            if o is None or ltok != o['tok'] or mpx > o['px'] + 1e-9:
                continue
            if self.c.queue:
                if o['qa'] > 0:
                    eat = min(o['qa'], sz); o['qa'] -= eat; sz -= eat
                if sz <= 0 and mpx > o['px'] - 1e-9:
                    continue
                if sz <= 0:                     # printed below us but queue absorbed it
                    continue
            got = min(o['rem'], sz)
            if got > 0:
                self.fills.append((o['tok'], o['px'], got))
                o['rem'] -= got
                self.nfill += 1
                if o['rem'] <= 1e-9:
                    self.order = None
                    o = None

    # ---- quoting decision --------------------------------------------------
    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead):
        c = self.c
        while self.pend and self.pend[0][0] <= t:
            _, act = self.pend.pop(0)
            act()
        if ub is None or ua is None or db is None or da is None or lead is None:
            return
        umid = (ub + ua) / 2.0
        fav_up = umid > 0.5
        fbid, fbs, fask = (ub, ubs, ua) if fav_up else (db, dbs, da)
        tok = 'U' if fav_up else 'D'
        agree = (lead > 0) == fav_up
        ok = (c.tl_lo <= tl <= c.tl_hi and abs(lead) >= c.lead_min and agree
              and self.nfill < c.max_fills)
        if c.mode == 'mid':                       # control: quote the mid, no gates
            ok = c.tl_lo <= tl <= c.tl_hi and self.nfill < c.max_fills
            px = round(fbid, 2)
        else:
            px = round(fbid + (TICK if (c.improve and fask - fbid > 1.5 * TICK) else 0.0), 2)
            ok = ok and (c.lo - 1e-9 <= px <= c.hi + 1e-9)
        o = self.order
        if not ok:
            if o is not None:
                self.pend.append((t + c.delay, self._cancel))
            return
        if o is None:
            qa = 0.0 if (c.improve and px > fbid + 1e-9) else (fbs or 0.0)
            self.pend.append((t + c.delay, self._place(tok, px, qa)))
        elif o['tok'] != tok or (c.chase and abs(o['px'] - px) > 1e-9):
            self.pend.append((t + c.delay, self._replace(tok, px, fbs or 0.0, fbid, c)))

    def _cancel(self):
        self.order = None

    def _place(self, tok, px, qa):
        def f():
            if self.order is None and self.nfill < self.c.max_fills:
                self.order = dict(tok=tok, px=px, qa=qa if self.c.queue else 0.0,
                                  rem=self.c.size)
        return f

    def _replace(self, tok, px, fbs, fbid, c):
        def f():
            rem = self.order['rem'] if self.order else c.size
            qa = 0.0 if (c.improve and px > fbid + 1e-9) else fbs
            self.order = dict(tok=tok, px=px, qa=qa if c.queue else 0.0, rem=rem)
        return f

    def settle(self, upwon):
        pnl = 0.0; shares = 0.0; notional = 0.0
        for tok, px, sz in self.fills:
            won = upwon if tok == 'U' else 1 - upwon
            pnl += sz * ((won - px) + REB * px * (1 - px))
            shares += sz; notional += sz * px
        return pnl, shares, notional, len(self.fills)


def run_file(args):
    path, wins, cfgs = args
    bars = {}
    prev_t = {}
    acc = [dict(pnl=0.0, sh=0.0, notional=0.0, fills=0, bars=0, wins=0, losses=0,
                daypnl=defaultdict(float)) for _ in cfgs]
    day = os.path.basename(path).split('-')[2]
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
                        ltok = 'D' if tbu else 'U'          # token the maker ends up long
                        pr.append((ts, ltok, (1 - upx) if tbu else upx, sz))
                    pr.sort()
                    for s in st:
                        s.on_prints(pr)
                t = d['t']
                for s in st:
                    s.on_snap(t, d['tl'], d['ub'], d['ubs'], d['ua'], d['uas'],
                              d['db'], d['dbs'], d['da'], d['das'], d['lead_bps'])
                prev_t[ws] = t
    except (EOFError, OSError, gzip.BadGzipFile) as e:
        print('FAIL', path, e, file=sys.stderr)
        return None
    for ws, st in bars.items():
        w = wins[ws]
        for i, s in enumerate(st):
            pnl, sh, no, nf = s.settle(w)
            a = acc[i]
            a['bars'] += 1
            if nf:
                a['pnl'] += pnl; a['sh'] += sh; a['notional'] += no; a['fills'] += nf
                a['daypnl'][day] += pnl
                for tok, px, sz in s.fills:
                    won = w if tok == 'U' else 1 - w
                    a['wins' if won else 'losses'] += 1
    return acc


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


def main(coins, cfgs):
    pool = Pool(10)
    totals = {c.name: dict(pnl=0.0, sh=0.0, notional=0.0, fills=0, bars=0,
                           wins=0, losses=0, daypnl=defaultdict(float)) for c in cfgs}
    for coin in coins:
        files = sorted(glob.glob(os.path.join(MREC, coin, f'{coin}-mrec-*.jsonl.gz')))
        wins = {}
        for p in pool.imap_unordered(res_scan, files, chunksize=4):
            wins.update(p)
        per = {c.name: dict(pnl=0.0, sh=0.0, fills=0, wins=0, losses=0) for c in cfgs}
        for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files], chunksize=2):
            if acc is None:
                continue
            for c, a in zip(cfgs, acc):
                T = totals[c.name]
                for k in ('pnl', 'sh', 'notional', 'fills', 'bars', 'wins', 'losses'):
                    T[k] += a[k]
                for d, v in a['daypnl'].items():
                    T['daypnl'][d] += v
                P = per[c.name]
                for k in ('pnl', 'sh', 'fills', 'wins', 'losses'):
                    P[k] += a[k]
        print(f'--- {coin} ---')
        for c in cfgs:
            P = per[c.name]
            if P['fills']:
                print(f"  {c.name:22s} fills {P['fills']:6d}  sh {P['sh']:9.0f}  "
                      f"win {P['wins']/(P['wins']+P['losses']):.3f}  "
                      f"pnl ${P['pnl']:8.2f}  {P['pnl']/P['sh']*100:+.3f} c/sh")
        sys.stdout.flush()
    print('\n===== TOTAL =====')
    for c in cfgs:
        T = totals[c.name]
        if not T['fills']:
            print(f"  {c.name:22s} NO FILLS"); continue
        days = len(T['daypnl'])
        dp = np.array(list(T['daypnl'].values()))
        print(f"  {c.name:22s} fills {T['fills']:6d}  sh {T['sh']:9.0f}  "
              f"win {T['wins']/(T['wins']+T['losses']):.3f}  "
              f"c/sh {T['pnl']/T['sh']*100:+.3f}  ${T['pnl']:8.2f} tot  "
              f"${T['pnl']/days:+7.2f}/day  t={dp.mean()/(dp.std(ddof=1)/math.sqrt(len(dp))):+5.2f}")
    return totals


if __name__ == '__main__':
    coins = sys.argv[1:] or ['btc']
    cfgs = [
        Cfg('base .90-.96'),
        Cfg('improve', improve=True),
        Cfg('NOQ(control)', queue=False),
        Cfg('MID(control)', mode='mid', lead_min=0),
        Cfg('wide .88-.97', lo=.88, hi=.97),
        Cfg('nolead', lead_min=0.0),
    ]
    main(coins, cfgs)
