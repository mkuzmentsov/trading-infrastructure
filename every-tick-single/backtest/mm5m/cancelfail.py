"""How much does the strategy degrade when protective cancels LOSE THE RACE?

Live 2026-08-19: 2 of 4 cancels returned ok=False because the order had already
filled. The sim assumed every cancel lands cleanly after cancel_delay. If the
gates (imb/fv/pull) frequently CANNOT pull a quote, their protective value is
overstated and the +$167/day headline needs discounting.

Model: when a cancel executes, with probability p_fail it is a no-op and the
order stays live (we could not pull it). Deterministic per (bar, token) so runs
are reproducible.
"""
import sys, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imbmm as I, fvmm as F, openmm2 as O


class CfgX(I.CfgI):
    def __init__(self, name, cancel_fail=0.0, **kw):
        super().__init__(name, **kw)
        self.cancel_fail = cancel_fail


class FailBar(I.ImbBar):
    def _cancel(self, tok):
        inner = super()._cancel(tok)
        def f():
            p = self.c.cancel_fail
            if p > 0:
                o = self.o.get(tok)
                if o is not None:
                    seed = f"{self._bar_key}-{tok}-{o.get('px')}-{len(self.fills)}"
                    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
                    if h < p:
                        return           # cancel lost the race: order stays live
            inner()
        return f

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        if not hasattr(self, '_bar_key'):
            self._bar_key = int(t)
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)


O.BarSim = FailBar

if __name__ == '__main__':
    cfgs = []
    for pf in (0.0, 0.25, 0.5, 0.75, 1.0):
        k = dict(F.BEST); k['delay'] = 0.2
        cfgs.append(CfgX(f'cancel_fail={pf:.0%}', fv_thr=0.08, imb_thr=0.2,
                         cancel_fail=pf, **k))
    O.main(sys.argv[1].split(','), cfgs)
