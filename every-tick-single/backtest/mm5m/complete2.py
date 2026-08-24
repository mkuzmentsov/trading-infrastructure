"""Maker-completion (improve 1 tick, no fee) + size scaling.

Taker completion failed: the fee peaks at p=.5 and the ceiling cut winners and
kept losers.  A completing leg placed one tick ABOVE the touch costs ~1c of
price but pays no fee and still earns the rebate.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O


class CfgC(F.CfgF):
    def __init__(self, name, comp_tl=None, comp_ticks=1, **kw):
        super().__init__(name, **kw)
        self.comp_tl = comp_tl
        self.comp_ticks = comp_ticks


class CompBar(F.FVBar):
    """the leg we are short gets placed comp_ticks ABOVE the touch to fill fast"""

    def _place(self, tok):
        c = self.c
        def f():
            if self.o[tok] is not None or self.nf[tok] >= c.max_fills or self.bk is None:
                return
            bid, bsz = self.bk[tok]
            other = 'D' if tok == 'U' else 'U'
            fme = sum(s for tk, _, s, _ in self.fills if tk == tok)
            fot = sum(s for tk, _, s, _ in self.fills if tk == other)
            completing = c.comp_tl is not None and fot > fme
            px = round(bid + (c.comp_ticks * O.TICK if completing else -c.offset * O.TICK), 2)
            if not (c.band[0] - 0.02 <= px <= c.band[1] + 0.02):
                return
            size = min(c.size, fot - fme) if completing else c.size
            if size <= 0:
                return
            self.o[tok] = dict(px=px, qa=(0.0 if completing else
                                          (bsz if c.queue else 0.0)),
                               rem=size, at_touch=not completing)
        return f

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        c = self.c
        # while completing, ignore the fv/pull gates for the missing leg -
        # the point is to flatten, not to express a view
        fu = sum(s for tk, _, s, _ in self.fills if tk == 'U')
        fd = sum(s for tk, _, s, _ in self.fills if tk == 'D')
        if c.comp_tl is not None and abs(fu - fd) > 1e-9 and tl <= c.comp_tl:
            miss = 'D' if fu > fd else 'U'
            if self.bk is not None and self.o[miss] is None:
                self.nf[miss] = 0
                self.pend.append((t + c.delay, self._place(miss)))
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)


O.BarSim = CompBar

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    mode = sys.argv[2] if len(sys.argv) > 2 else 'comp'
    if mode == 'comp':
        cfgs = [CfgC('no completion', fv_thr=0.08, **F.BEST)]
        for ctl, tk in ((238, 1), (238, 2), (200, 1), (120, 1), (60, 1)):
            cfgs.append(CfgC(f'mkr-comp tl<={ctl} +{tk}t', fv_thr=0.08,
                             comp_tl=ctl, comp_ticks=tk, **F.BEST))
    else:
        cfgs = []
        for sz in (10, 25, 50, 100, 200):
            k = dict(F.BEST); k['size'] = sz
            cfgs.append(CfgC(f'size={sz}', fv_thr=0.08, **k))
    O.main(coins, cfgs)
