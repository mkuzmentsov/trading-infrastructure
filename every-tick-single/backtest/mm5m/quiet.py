"""Latency robustness via a QUIET filter.

Adverse selection comes from fair value moving under a stale quote.  PM 5m
price moves ~4.4c per bps of spot, so quote only when recent realised spot
movement is small - then a 200-400ms stale quote is not actually stale.
If this works the strategy stops being a latency race we might lose.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O


class CfgQ(F.CfgF):
    def __init__(self, name, quiet_bps=None, quiet_win=2.0, **kw):
        super().__init__(name, **kw)
        self.quiet_bps = quiet_bps
        self.quiet_win = quiet_win


class QuietBar(F.FVBar):
    def _is_quiet(self, t):
        c = self.c
        if c.quiet_bps is None or len(self.lead_h) < 3:
            return True
        t0 = t - c.quiet_win
        vals = [ld for ts, ld in self.lead_h if ts >= t0]
        if len(vals) < 3:
            return True
        return (max(vals) - min(vals)) <= c.quiet_bps

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        if lead is not None and not self._is_quiet(t):
            # stand down entirely while spot is moving
            self._decay(dt, tl)
            self.lead_h.append((t, lead))
            if ub is not None and db is not None:
                self.bk = {'U': (ub, ubs or 0.0), 'D': (db, dbs or 0.0)}
            while self.pend and self.pend[0][0] <= t:
                self.pend.pop(0)[1]()
            for tok in ('U', 'D'):
                if self.o[tok] is not None:
                    self.pend.append((t + self.c.cancel_delay, self._cancel(tok)))
            return
        super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)


O.BarSim = QuietBar

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = []
    for dly in (0.1, 0.2, 0.4):
        k = dict(F.BEST); k['delay'] = dly
        cfgs.append(CfgQ(f'd={dly} no quiet', fv_thr=0.08, **k))
        for q in (0.5, 1.0, 2.0):
            cfgs.append(CfgQ(f'd={dly} quiet<={q}bps/2s', fv_thr=0.08,
                             quiet_bps=q, quiet_win=2.0, **k))
    O.main(coins, cfgs)
