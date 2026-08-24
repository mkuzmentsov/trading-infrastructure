"""PATIENT quoting: place once, let queue position ACCRUE, never re-pin.

Hypothesis for the field-vs-sim gap: re-pinning resets us to the back of the
queue every time, so we only ever fill when our level is SWEPT (the toxic
subset).  The queue half-life is 1.3-2.3s, so an order left alone ages to the
FRONT and catches the small benign prints first.
Crucially this design is latency-INSENSITIVE: an order we never move does not
care about the 190ms venue round trip.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, deepmm as D, openmm2 as O


class CfgP(F.CfgF):
    def __init__(self, name, patient=True, **kw):
        super().__init__(name, **kw)
        self.patient = patient


class PatientBar(F.FVBar):
    """once placed, the order is left alone until the window closes"""

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        c = self.c
        if not c.patient:
            return super().on_snap(t, tl, ub, ubs, ua, uas, db, dbs, da, das,
                                   lead, dt)
        self._decay(dt, tl)
        if lead is not None:
            self.lead_h.append((t, lead))
        if ub is not None and db is not None:
            self.bk = {'U': (ub, ubs or 0.0), 'D': (db, dbs or 0.0)}
        while self.pend and self.pend[0][0] <= t:
            self.pend.pop(0)[1]()
        if self.bk is None:
            return
        in_window = c.tl_lo <= tl <= c.tl_hi
        mv = self._spot_move(t) if c.pull_bps is not None else None
        edge = None
        if (c.fv_thr is not None and lead is not None
                and ub is not None and ua is not None):
            edge = F.phi(lead / F.sigma(tl)) - (ub + ua) / 2.0
        for tok in ('U', 'D'):
            bid, _ = self.bk[tok]
            o = self.o[tok]
            if o is not None:
                o['at_touch'] = o['px'] >= bid - 1e-9
                if not in_window:                       # window closed -> pull
                    self.pend.append((t + c.cancel_delay, self._cancel(tok)))
                continue                                # otherwise LEAVE IT
            if not in_window or self.nf[tok] >= c.max_fills:
                continue
            px = round(bid - c.offset * O.TICK, 2)
            if not (c.band[0] <= px <= c.band[1]):
                continue
            if mv is not None:
                adverse = -mv if tok == 'U' else mv
                if adverse >= c.pull_bps:
                    continue
            if edge is not None:
                e = edge if tok == 'U' else -edge
                if e < -c.fv_thr:
                    continue
            self.pend.append((t + c.delay, self._place(tok)))


O.BarSim = PatientBar
BASE = dict(F.BEST)

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = []
    for dly in (0.2, 0.4):
        for off in (0, 1, 2):
            k = dict(BASE); k['delay'] = dly; k['offset'] = off; k['repin'] = False
            cfgs.append(CfgP(f'patient d{dly} off{off}', fv_thr=0.08, **k))
    k = dict(BASE); k['delay'] = 0.2; k['repin'] = True
    cfgs.append(CfgP('REPIN d0.2 (control)', fv_thr=0.08, patient=False, **k))
    k = dict(BASE); k['delay'] = 0.2; k['offset'] = 0; k['repin'] = False
    cfgs.append(CfgP('patient d0.2 RAND', fv_thr=0.08, rand=True, **k))
    O.main(coins, cfgs)
