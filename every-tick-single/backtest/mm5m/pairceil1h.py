"""Should the PAIR CEILING accept slightly-LOSING pairs to avoid naked legs?

Live 1h decomposition (35 bars): pairs +3.01 c/pair-share, residual
-13.98 c/sh. And 87% of bars DO oscillate enough to reach both legs — so legs
go unpaired mostly because the ceiling REFUSES the second leg once the first
filled rich (cap = CEIL - p), not because the market ran away.

If a naked leg costs ~14c and a slightly-over-par pair costs 1-3c, the ceiling
may be mispriced. Sweep PAIR_CEIL from 0.985 (current, strict) to 1.05 (accept
losing pairs) to OFF, on the 1h archive.

Outcomes derived from the settled post-role book (1h recorder predates RES).
"""
import gzip, json, os, sys, glob, math
from multiprocessing import Pool
from collections import defaultdict
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MREC = os.path.abspath(os.path.join(ROOT, '..', '..', 'data', 'mrec'))
REB, TICK = 0.20 * 0.07, 0.01


class Cfg:
    def __init__(self, name, ceil=0.985, edge=0.015, size=10.0, batch=5.0,
                 delay=0.5, queue=True, mid_lo=0.12, mid_hi=0.88,
                 quit_tl=60.0, warmup=10.0, rand=False, exit_tl=None, exit_age=None, take_age=None):
        self.__dict__.update(locals()); del self.self


class Bar:
    __slots__ = ('c', 'o', 'inv', 'cost', 'pend', 'fills', 'pairpnl', 'exitpnl', 'bk', 'imb_since', 'takepnl', 'depths', 'curmid')

    def __init__(self, cfg):
        self.c = cfg
        self.o = {'U': None, 'D': None}
        self.inv = {'U': 0.0, 'D': 0.0}
        self.cost = {'U': 0.0, 'D': 0.0}
        self.pend = []
        self.fills = 0
        self.pairpnl = 0.0
        self.exitpnl = 0.0
        self.bk = None
        self.imb_since = None
        self.takepnl = 0.0
        self.depths = []
        self.curmid = None

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
                if self.curmid is not None:
                    m = self.curmid if ltok == 'U' else 1.0 - self.curmid
                    self.depths.append(((m - o['px']) * 100, got))
                self.inv[ltok] += got
                self.cost[ltok] += got * o['px']
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
        self.curmid = mid
        self.bk = {'U': ub, 'D': db}
        # CUT THE NAKED LEG instead of holding it to resolution. Measured:
        # an unpaired leg is worth about -47c/share (it is unpaired BECAUSE the
        # market moved against it), while selling back costs ~ spread/2 + the
        # taker fee ~= 2.5c. poolfarm's hold-to-redemption rule was written for
        # below-mid fills that were +EV to hold; that does not apply here.
        # EXIT-BY-AGE: cut a leg that has been unpaired for > exit_age seconds.
        # Timing is everything — a leg stranded for MINUTES is already -47c
        # (the market moved, and the bid reflects it), but one cut SECONDS after
        # the fill costs only the spread. The earlier exit_tl test cut at a
        # fixed time before bar CLOSE, i.e. always far too late, which is why it
        # made things worse.
        ex0 = self.inv['U'] - self.inv['D']
        if abs(ex0) > 1e-6:
            if self.imb_since is None:
                self.imb_since = t
        else:
            self.imb_since = None
        # TAKER COMPLETION: rather than strand a leg, CROSS and buy the missing
        # side at the ask. Unlike the 5m attempt this is UNCONDITIONAL (no pair
        # ceiling gate) — gating it there meant only completing when the other
        # side was cheap, i.e. cutting winners and keeping losers.
        if (self.c.take_age is not None and self.imb_since is not None
                and t - self.imb_since >= self.c.take_age and abs(ex0) > 1e-6):
            miss = 'D' if ex0 > 0 else 'U'
            ask = {'U': ua, 'D': da}[miss]
            n = abs(ex0)
            if ask and 0.01 < ask < 0.99:
                fee = 0.07 * ask * (1 - ask)
                self.inv[miss] += n
                self.cost[miss] += n * (ask + fee)
                self.takepnl -= n * fee
                self.imb_since = None
        if (self.c.exit_age is not None and self.imb_since is not None
                and t - self.imb_since >= self.c.exit_age):
            tok = 'U' if ex0 > 0 else 'D'
            n = abs(ex0); bid = {'U': ub, 'D': db}[tok]
            if bid and bid > 0.01 and self.inv[tok] > 0:
                avg = self.cost[tok] / self.inv[tok]
                fee = 0.07 * bid * (1 - bid)
                self.exitpnl += n * (bid - avg - fee)
                self.inv[tok] -= n; self.cost[tok] -= n * avg
                self.imb_since = None
        if self.c.exit_tl is not None and tl <= self.c.exit_tl:
            ex = self.inv['U'] - self.inv['D']
            if abs(ex) > 1e-6:
                tok = 'U' if ex > 0 else 'D'
                n = abs(ex); bid = self.bk[tok]
                if bid and bid > 0.01:
                    avg = self.cost[tok] / self.inv[tok]
                    fee = 0.07 * bid * (1 - bid)
                    self.exitpnl += n * (bid - avg - fee)
                    self.inv[tok] -= n
                    self.cost[tok] -= n * avg
        live = (c.quit_tl < tl and (3600.0 - tl) > c.warmup
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
            if ok and px >= m - 0.004:      # never rest at/above this side's mid
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
            self.o[tok] = dict(px=px, rem=rem,
                               qa=(bsz if self.c.queue else 0.0))
        return f

    def settle(self, upwon):
        pnl = 0.0
        npair0 = min(self.inv['U'], self.inv['D'])
        pairpnl = 0.0
        if npair0 > 0:
            au = self.cost['U']/self.inv['U']; ad = self.cost['D']/self.inv['D']
            pairpnl = npair0 * (1.0 - au - ad)
        self.pairpnl = pairpnl
        pnl += self.exitpnl
        for tok in ('U', 'D'):
            if self.inv[tok] <= 0:
                continue
            won = upwon if tok == 'U' else 1 - upwon
            avg = self.cost[tok] / self.inv[tok]
            pnl += self.inv[tok] * ((won - avg) + REB * avg * (1 - avg))
        npair = min(self.inv['U'], self.inv['D'])
        nres = abs(self.inv['U'] - self.inv['D'])
        return pnl, npair, nres, self.fills


def derive_wins(path):
    last = {}
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                if '"role":"post"' not in line:
                    continue
                d = json.loads(line)
                px = d.get('ub') if d.get('ub') is not None else d.get('ua')
                if px is None:
                    continue
                k = d['ws']
                if k not in last or d['t'] >= last[k][0]:
                    last[k] = (d['t'], px)
    except Exception:
        return {}
    return {k: (1 if p > 0.5 else 0) for k, (t, p) in last.items()
            if p > 0.9 or p < 0.1}


def run_file(args):
    path, wins, cfgs = args
    bars = {}
    acc = [dict(pnl=0.0, npair=0.0, nres=0.0, fills=0, bars=0, pp=0.0, ex=0.0, dsum=0.0, dn=0.0, dneg=0.0) for _ in cfgs]
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
                w = (ws // 3600) % 2
            pnl, npair, nres, nf = s.settle(w)
            a = acc[i]; a['bars'] += 1
            a['pnl'] += pnl; a['npair'] += npair; a['nres'] += nres; a['fills'] += nf
            a['pp'] += getattr(s, 'pairpnl', 0.0)
            a['ex'] += getattr(s, 'exitpnl', 0.0)
            for dd, ww in s.depths:
                a['dsum'] += dd*ww; a['dn'] += ww
                if dd < 0: a['dneg'] += ww
    return acc


if __name__ == '__main__':
    coin = 'btc'
    files = sorted(glob.glob(os.path.join(MREC, coin + '-mrec1h',
                                          f'{coin}-mrec1h-*.jsonl.gz')))
    assert files, 'NO FILES'
    pool = Pool(10)
    wins = {}
    for w in pool.imap_unordered(derive_wins, files, chunksize=4):
        wins.update(w)
    # search the promising corner: SHALLOW quoting (high fill rate, few naked
    # legs) x a ceiling just tight enough to keep pairs at/below par.
    cfgs = [Cfg('e1.5 ceilON', edge=0.015, ceil=0.985),
            Cfg('e0.5 ceilOFF', edge=0.005, ceil=None),
            Cfg('e2.5 ceilON', edge=0.025, ceil=0.985)]
    T = [dict(pnl=0.0, npair=0.0, nres=0.0, fills=0, bars=0, pp=0.0, ex=0.0, dsum=0.0, dn=0.0, dneg=0.0) for _ in cfgs]
    for acc in pool.imap_unordered(run_file, [(p, wins, cfgs) for p in files],
                                   chunksize=2):
        if acc is None:
            continue
        for t, a in zip(T, acc):
            for k in t:
                t[k] += a[k]
    print(f'1h btc, {len(wins)} resolved bars')
    print(f"  {'config':22s} {'pairsh':>7s} {'ressh':>6s} {'res%':>5s} "
          f"{'pair$':>8s} {'resid$':>8s} {'PnL':>9s} {'$/bar':>7s}")
    for c, t in zip(cfgs, T):
        tot = t['npair'] * 2 + t['nres']
        if tot <= 0:
            print(f"  {c.name:18s} no fills"); continue
        dmean = t['dsum']/t['dn'] if t['dn'] else 0.0
        dneg = t['dneg']/t['dn']*100 if t['dn'] else 0.0
        print(f"  {c.name:22s} depth@fill={dmean:+5.2f}c  filled_ABOVE_mid={dneg:4.0f}%")
        print(f"  {'':22s} {t['npair']:7.0f} {t['nres']:6.0f} "
              f"{t['nres']/tot*100:4.0f}% {t['pp']:8.2f} {t['pnl']-t['pp']:8.2f} "
              f"{t['pnl']:9.2f} {t['pnl']/max(1,t['bars']):7.3f}")
