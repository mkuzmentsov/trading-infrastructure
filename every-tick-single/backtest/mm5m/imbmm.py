"""IMBMM - gate quoting on top-of-book queue imbalance.

Field data (ofi.py): in our exact cell, at-touch maker fills run -1.27 c/sh
gross when our side's queue is thin vs the opposite, and +2.64 when it is
thick - monotone over 6 buckets.

NOTE the book is mirrored (ubs == das, uas == dbs) so imb_UP == -imb_DOWN:
this gate is inherently ONE-SIDED and gives up the pair engine.  The bet is
that each leg is individually +EV instead.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O


class CfgI(F.CfgF):
    def __init__(self, name, imb_thr=None, **kw):
        super().__init__(name, **kw)
        self.imb_thr = imb_thr


class ImbBar(F.FVBar):
    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        c = self.c
        self._imb = {'U': None, 'D': None}
        if c.imb_thr is not None:
            for tok, myq, oppq in (('U', ubs, uas), ('D', dbs, das)):
                myq = myq or 0.0
                oppq = oppq or 0.0
                tot = myq + oppq
                self._imb[tok] = (myq - oppq) / tot if tot > 0 else 0.0
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)

    def _place(self, tok):
        c = self.c
        inner = super()._place(tok)
        def f():
            if c.imb_thr is not None:
                i = getattr(self, '_imb', {}).get(tok)
                if i is None or i < c.imb_thr:
                    return
            inner()
        return f


# gate also has to PULL an existing quote when imbalance turns against us
_orig = ImbBar.on_snap
def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
    _orig(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)
    c = self.c
    if c.imb_thr is None:
        return
    for tok in ('U', 'D'):
        o = self.o[tok]
        i = self._imb.get(tok)
        if o is not None and i is not None and i < c.imb_thr - 0.15:
            self.pend.append((t + c.cancel_delay, self._cancel(tok)))
ImbBar.on_snap = on_snap

O.BarSim = ImbBar

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = []
    for dly in (0.2, 0.4):
        for thr in (None, 0.2, 0.4, 0.6):
            k = dict(F.BEST); k['delay'] = dly
            cfgs.append(CfgI(f'd{dly} imb>={thr}', fv_thr=0.08, imb_thr=thr, **k))
    k = dict(F.BEST); k['delay'] = 0.2
    cfgs.append(CfgI('d0.2 imb>=0.4 RAND', fv_thr=0.08, imb_thr=0.4, rand=True, **k))
    O.main(coins, cfgs)
