"""How much does the edge depend on RE-PINNING?  Each re-pin needs a fresh
EIP-712 signature (~100-300ms CPU, single-use), so places/bar is a hard
engineering budget, not a free parameter."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O
if __name__ == '__main__':
    cfgs = []
    for rp in (True, False):
        for dly in (0.1, 0.2):
            k = dict(F.BEST); k['repin'] = rp; k['delay'] = dly
            cfgs.append(F.CfgF(f'repin={rp} d={dly}', fv_thr=0.08, **k))
    O.main(sys.argv[1].split(','), cfgs)
