"""SKEWMM — use queue imbalance as a PRICE SKEW, not an on/off gate.

Problem with imbmm (§11): the book is mirrored, so imb_UP == -imb_DOWN. A hard
imbalance gate is therefore ONE-SIDED by construction — it bought edge by
destroying the pair engine (pair% 57->24-38%, pair income $73->$18/day), and
~85% of PnL became directional residual with ~$200/day std.

Idea: quote BOTH sides always, but skew the PRICE by imbalance —
  favoured side  (imb >= thr): join the touch
  unfavoured side            : rest `skew` ticks BELOW the touch
This keeps pairs completable, makes adverse fills rarer, and buys the bad leg
CHEAPER, which lowers the pair sum directly (a pair only pays if sum < 1).

Also adds the PAIR CEILING the live bot enforces but the sim never modelled —
once one leg fills at p, the other is capped at PAIR_CEIL - p.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imbmm as I, fvmm as F, openmm2 as O

TICK = O.TICK


class CfgS(I.CfgI):
    def __init__(self, name, skew=1, skew_thr=0.2, pair_ceil=None, **kw):
        super().__init__(name, **kw)
        self.skew = skew                  # ticks below touch on the bad side
        self.skew_thr = skew_thr
        self.pair_ceil = pair_ceil        # None = off (old sim behaviour)


class SkewBar(I.ImbBar):
    def _avg_px(self, tok):
        f = [(px, sz) for tk, px, sz, _ in self.fills if tk == tok]
        if not f:
            return None
        return sum(p * s for p, s in f) / sum(s for _, s in f)

    def _place(self, tok):
        c = self.c
        skew = getattr(c, 'skew', None)
        thr = getattr(c, 'skew_thr', 0.2)
        ceil = getattr(c, 'pair_ceil', None)
        gate = getattr(c, 'imb_thr', None)   # hard gate (None = skew mode)
        def f():
            if self.o[tok] is not None or self.nf[tok] >= c.max_fills or self.bk is None:
                return
            bid, bsz = self.bk[tok]
            i = getattr(self, '_imb', {}).get(tok)
            if gate is not None:
                # HARD GATE: quote only the favoured side, at the touch
                if i is None or i < gate:
                    return
                off = 0
            else:
                # SKEW: both sides always quoted, bad side deeper
                off = 0 if (i is not None and i >= thr) else (skew or 0)
            px = round(bid - off * TICK, 2)
            if not (c.band[0] <= px <= c.band[1]):
                return
            if ceil is not None:
                other = 'D' if tok == 'U' else 'U'
                ap = self._avg_px(other)
                if ap is not None and px > ceil - ap + 1e-9:
                    return                      # would lock a losing pair
            at_touch = off == 0
            qa = (bsz if c.queue else 0.0) if at_touch else (bsz * 1.0 if c.queue else 0.0)
            self.o[tok] = dict(px=px, qa=qa, rem=c.size, at_touch=at_touch)
            self.nplace += 1
        return f

    def on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt):
        # imbalance must be available to _place; compute before the base call
        self._imb = {}
        for tok, myq, oppq in (('U', ubs, uas), ('D', dbs, das)):
            myq = myq or 0.0; oppq = oppq or 0.0
            tot = myq + oppq
            self._imb[tok] = (myq - oppq) / tot if tot > 0 else 0.0
        # skew cfgs bypass ImbBar's hard gate + its adverse-imbalance pull
        F.FVBar.on_snap(self, t, tl, ub, ubs, ua, uas, db, dbs, da, das, lead, dt)


O.BarSim = SkewBar

if __name__ == '__main__':
    cfgs = []
    k0 = dict(F.BEST); k0['delay'] = 0.2
    # controls: the two designs we already know
    cfgs.append(I.CfgI('A: hard gate imb>=0.2', fv_thr=0.08, imb_thr=0.2, **k0))
    for skew in (1, 2, 3):
        cfgs.append(CfgS(f'B: skew {skew}t (no ceil)', fv_thr=0.08, imb_thr=None,
                         skew=skew, **k0))
        cfgs.append(CfgS(f'C: skew {skew}t + ceil', fv_thr=0.08, imb_thr=None,
                         skew=skew, pair_ceil=0.985, **k0))
    O.main(sys.argv[1].split(','), cfgs)
