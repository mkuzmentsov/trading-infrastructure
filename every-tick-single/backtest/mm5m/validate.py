import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O
BEST = dict(F.BEST)
if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = [F.CfgF('BEST fv.08', fv_thr=0.08, **BEST),
            F.CfgF('BEST no-fv',  **BEST),
            F.CfgF('RAND ctrl',  fv_thr=0.08, rand=True, **BEST),
            F.CfgF('NOQ ctrl',   fv_thr=0.08, queue=False, **BEST)]
    O.main(coins, cfgs)
