"""Back to the PAIR ENGINE — the only component that was ever robust
(t=+8.7, positive 19/19 days) — now WITH the pair ceiling the sim never had,
and at our MEASURED latency (~91ms place / 71ms cancel), not the assumed 200ms.

RAND control is the benchmark that matters: real >> RAND means genuine
selection; real ~ RAND means the PnL is structural (spread + guaranteed pairs).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skewmm as S, fvmm as F, openmm2 as O
O.BarSim = S.SkewBar
if __name__ == '__main__':
    cfgs = []
    for dly in (0.1, 0.2):
        k = dict(F.BEST); k['delay'] = dly
        # pure pair engine: both sides at the touch, no imbalance gate, + ceiling
        cfgs.append(S.CfgS(f'PAIR d{dly} +ceil', fv_thr=0.08, imb_thr=None,
                           skew=0, skew_thr=-9, pair_ceil=0.985, **k))
        cfgs.append(S.CfgS(f'PAIR d{dly} +ceil RAND', fv_thr=0.08, imb_thr=None,
                           skew=0, skew_thr=-9, pair_ceil=0.985, rand=True, **k))
        cfgs.append(S.CfgS(f'GATE d{dly} +ceil', fv_thr=0.08, imb_thr=0.2,
                           skew=None, pair_ceil=0.985, **k))
    O.main(sys.argv[1].split(','), cfgs)
