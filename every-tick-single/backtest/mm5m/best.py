"""The untested combination: HARD GATE + PAIR CEILING (the live bot has both;
no sim ever had the ceiling)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skewmm as S, fvmm as F, openmm2 as O
O.BarSim = S.SkewBar
if __name__ == '__main__':
    cfgs = []
    k = dict(F.BEST); k['delay'] = 0.2
    for g in (0.2, 0.4):
        cfgs.append(S.CfgS(f'gate{g} NO ceil', fv_thr=0.08, imb_thr=g, skew=None,
                           pair_ceil=None, **k))
        cfgs.append(S.CfgS(f'gate{g} + ceil', fv_thr=0.08, imb_thr=g, skew=None,
                           pair_ceil=0.985, **k))
    cfgs.append(S.CfgS('gate0.2+ceil RAND', fv_thr=0.08, imb_thr=0.2, skew=None,
                       pair_ceil=0.985, rand=True, **k))
    cfgs.append(S.CfgS('skew3+ceil (best skew)', fv_thr=0.08, imb_thr=None,
                       skew=3, pair_ceil=0.985, **k))
    O.main(sys.argv[1].split(','), cfgs)
