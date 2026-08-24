"""Does MIN_REST (anti-thrash) destroy the imbalance edge?

The first paper run churned 49 orders in ~50s: live top-of-book sizes update
per WS event and are far noisier than the 100ms snapshots this sim runs on, so
`imb` whipsaws across the gate line. MIN_REST holds a quote against soft gate
flips; COOLDOWN spaces re-placement. Both DELAY our reaction, so they must be
proven not to eat the edge before shipping.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imbmm as I, fvmm as F, openmm2 as O


class CfgR(I.CfgI):
    def __init__(self, name, min_rest=0.0, cooldown=0.0, **kw):
        super().__init__(name, **kw)
        self.min_rest = min_rest
        self.cooldown = cooldown


class RestBar(I.ImbBar):
    def _place(self, tok):
        inner = super()._place(tok)
        def f():
            cool = getattr(self, '_coolt', {})
            if cool.get(tok, 0.0) > self._now:
                return
            inner()
            o = self.o.get(tok)
            if o is not None and 't0' not in o:
                o['t0'] = self._now
        return f

    def _cancel(self, tok):
        inner = super()._cancel(tok)
        def f():
            if not hasattr(self, '_coolt'):
                self._coolt = {}
            self._coolt[tok] = self._now + self.c.cooldown
            inner()
        return f

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        self._now = t
        if self.c.min_rest > 0:
            # freeze soft-gate cancels for orders younger than min_rest by
            # temporarily hiding them from the gate logic
            held = {}
            for tok in ('U', 'D'):
                o = self.o.get(tok)
                if o is not None and t - o.get('t0', t) < self.c.min_rest:
                    held[tok] = o
            if held:
                npend = len(self.pend)
                super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)
                # drop any cancel scheduled this tick for a held order
                self.pend = self.pend[:npend] + [
                    p for p in self.pend[npend:]
                    if not getattr(p[1], '_is_cancel', False)]
                return
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)


# tag cancel closures so the hold filter can spot them
_oc = I.ImbBar._cancel
def _cancel_tagged(self, tok):
    f = _oc(self, tok)
    f._is_cancel = True
    return f
I.ImbBar._cancel = _cancel_tagged

O.BarSim = RestBar

if __name__ == '__main__':
    cfgs = []
    for mr, cd in ((0.0, 0.0), (1.0, 0.5), (1.5, 1.0), (3.0, 1.0)):
        k = dict(F.BEST); k['delay'] = 0.2
        cfgs.append(CfgR(f'min_rest={mr} cool={cd}', fv_thr=0.08, imb_thr=0.2,
                         min_rest=mr, cooldown=cd, **k))
    O.main(sys.argv[1].split(','), cfgs)
