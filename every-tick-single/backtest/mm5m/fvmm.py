"""FVMM - quote around OUR fair value, not the book's touch.

sigma(tl) calibrated in fairval.py (grid-searched against realised outcomes).
edge = Phi(lead/sigma) - mid  predicts the mid's own drift (corr +0.05/+0.08/
+0.12 at 1/3/10s), so it says which side is about to be adversely selected:
  quote UP   only while edge >= -thr
  quote DOWN only while edge <= +thr
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deepmm as D, openmm2 as O

SIG = {0: 2.00, 15: 2.50, 30: 2.75, 45: 3.00, 60: 3.25, 75: 3.50, 90: 3.50,
       105: 4.00, 120: 4.25, 135: 4.75, 150: 5.25, 165: 5.75, 180: 6.00,
       195: 6.50, 210: 6.75, 225: 7.00, 240: 7.75, 255: 8.25, 270: 8.50, 285: 8.25}


def sigma(tl):
    return SIG.get(int(tl // 15) * 15, 8.25)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


class CfgF(D.Cfg2):
    def __init__(self, name, fv_thr=None, **kw):
        super().__init__(name, **kw)
        self.fv_thr = fv_thr


class FVBar(D.DeepBar):
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
        edge = None
        if c.fv_thr is not None and lead is not None and ub is not None and ua is not None:
            edge = phi(lead / sigma(tl)) - (ub + ua) / 2.0
        for tok in ('U', 'D'):
            bid, _ = self.bk[tok]
            o = self.o[tok]
            if o is not None:
                o['at_touch'] = o['px'] >= bid - 1e-9
            want = live and self.nf[tok] < c.max_fills
            if want and mv is not None:
                adverse = -mv if tok == 'U' else mv
                if adverse >= c.pull_bps:
                    want = False
            if want and edge is not None:
                e = edge if tok == 'U' else -edge
                if e < -c.fv_thr:
                    want = False
            if not want:
                if o is not None:
                    self.pend.append((t + c.cancel_delay, self._cancel(tok)))
                continue
            if o is None:
                self.pend.append((t + c.delay, self._place(tok)))
            elif c.repin:
                px_now = round(bid - c.offset * O.TICK, 2)
                if abs(o['px'] - px_now) > 1e-9:
                    self.pend.append((t + c.delay, self._replace(tok)))


O.BarSim = FVBar
BEST = dict(offset=0, repin=True, delay=0.1, pull_bps=0.1, pull_win=0.5,
            tl_lo=240, tl_hi=297, band=(0.44, 0.56))

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = [CfgF('no fv gate', **BEST)]
    for thr in (0.15, 0.08, 0.05, 0.03, 0.02, 0.01):
        cfgs.append(CfgF(f'fv thr={thr}', fv_thr=thr, **BEST))
    cfgs.append(CfgF('fv .03 RAND', fv_thr=0.03, rand=True, **BEST))
    O.main(coins, cfgs)
