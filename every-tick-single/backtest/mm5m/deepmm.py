"""DEEPMM - rest BELOW the touch and let sweeps come to us.

Field data says the maker's PnL is ordered by posture:
   improved (better than touch) -1.38 c/sh  <  at touch +0.57  <  swept-deep +3.44
and at-touch fills from 500+ share prints pay +8.62 c/sh.  So the edge is
ABSORBING dislocating takers, not standing at the touch to be drifted past.

Design: place ONE fixed-price bid per token, `offset` ticks below the touch,
never reprice (repricing is what turns us into the aggressive bid), cancel only
when the window/band closes.  Queue ahead at a deep level is unobservable
(top-of-book data), so it is a swept parameter - deep_q x the touch size.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openmm2 as O
import math


class Cfg2(O.Cfg):
    def __init__(self, name, deep_q=1.0, repin=False, **kw):
        super().__init__(name, **kw)
        self.deep_q = deep_q
        self.repin = repin


class DeepBar(O.BarSim):
    """fixed-price placement; at_touch recomputed each snap; no stale-cancel."""

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
            o = self.o[tok]
            if o is not None:
                o['at_touch'] = o['px'] >= bid - 1e-9      # we are at/above the touch
            want = live and self.nf[tok] < c.max_fills
            if want and mv is not None:
                adverse = -mv if tok == 'U' else mv
                if adverse >= c.pull_bps:
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

    def _replace(self, tok):
        def f():
            self.o[tok] = None
            self._place(tok)()
        return f

    def _place(self, tok):
        c = self.c
        def f():
            if self.o[tok] is not None or self.nf[tok] >= c.max_fills or self.bk is None:
                return
            bid, bsz = self.bk[tok]
            px = round(bid - c.offset * O.TICK, 2)
            if not (c.band[0] <= px <= c.band[1]):
                return
            at_touch = c.offset == 0
            qa = (bsz if at_touch else bsz * c.deep_q) if c.queue else 0.0
            self.o[tok] = dict(px=px, qa=qa, rem=c.size, at_touch=at_touch)
            self.nplace += 1
        return f


O.BarSim = DeepBar

if __name__ == '__main__':
    coins = sys.argv[1].split(',') if len(sys.argv) > 1 else ['btc']
    cfgs = [
        Cfg2('touch (repin)',    offset=0, repin=True),
        Cfg2('deep1 fixed',      offset=1),
        Cfg2('deep2 fixed',      offset=2),
        Cfg2('deep3 fixed',      offset=3),
        Cfg2('deep4 fixed',      offset=4),
        Cfg2('deep2 q=2',        offset=2, deep_q=2.0),
        Cfg2('deep2 q=0.5',      offset=2, deep_q=0.5),
        Cfg2('deep3 fullbar',    offset=3, tl_lo=45),
        Cfg2('deep3 RAND',       offset=3, rand=True),
        Cfg2('deep3 NOQ',        offset=3, queue=False),
    ]
    O.main(coins, cfgs)
