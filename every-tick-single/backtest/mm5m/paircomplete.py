"""Kill the residual: complete unpaired legs with a TAKER order.

The pair engine is +$48.55/day at t=+7.11 (19/19 days).  The residual leg is
zero-mean (-$4.52/day, t=-0.08) but carries +/-$250 daily swings - fatal on a
~$95 bankroll.  Completing an unpaired leg by crossing costs the taker fee
(0.07*p(1-p) ~ 1.75c at p=.5) plus the 1c spread, so it is only worth doing
when the two legs still sum below a ceiling.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, deepmm as D, openmm2 as O


class CfgP(F.CfgF):
    def __init__(self, name, comp_tl=None, pair_ceil=1.00, **kw):
        super().__init__(name, **kw)
        self.comp_tl = comp_tl          # start completing once tl <= this
        self.pair_ceil = pair_ceil


class PairBar(F.FVBar):
    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)
        c = self.c
        if c.comp_tl is None or tl > c.comp_tl or ua is None or da is None:
            return
        fu = sum(s for tk, _, s, _ in self.fills if tk == 'U')
        fd = sum(s for tk, _, s, _ in self.fills if tk == 'D')
        if abs(fu - fd) < 1e-9:
            return
        if fu > fd:
            need, tok, ask, asz = fu - fd, 'D', da, das
            have_px = sum(px * s for tk, px, s, _ in self.fills if tk == 'U') / fu
        else:
            need, tok, ask, asz = fd - fu, 'U', ua, uas
            have_px = sum(px * s for tk, px, s, _ in self.fills if tk == 'D') / fd
        if ask is None or asz is None or asz <= 0:
            return
        if have_px + ask > c.pair_ceil + 1e-9:
            return
        got = min(need, asz)
        if got > 0:
            self.fills.append((tok, ask, got, True))     # True = taker leg


O.BarSim = PairBar

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = [CfgP('no completion', fv_thr=0.08, **F.BEST)]
    for ceil in (0.98, 0.99, 1.00, 1.02):
        cfgs.append(CfgP(f'comp tl<=200 c={ceil}', fv_thr=0.08, comp_tl=200,
                         pair_ceil=ceil, **F.BEST))
    for ctl in (238, 150, 60):
        cfgs.append(CfgP(f'comp tl<={ctl} c=1.00', fv_thr=0.08, comp_tl=ctl,
                         pair_ceil=1.00, **F.BEST))
    O.main(coins, cfgs)
