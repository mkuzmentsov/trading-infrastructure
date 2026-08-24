"""Which leg of the latency budget actually matters - the place or the cancel?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O
if __name__ == '__main__':
    cfgs = []
    for pl, cd in ((0.1, 0.1), (0.4, 0.1), (0.1, 0.4), (0.4, 0.4), (0.3, 0.1), (0.2, 0.1)):
        k = dict(F.BEST); k['delay'] = pl; k['cancel_delay'] = cd
        cfgs.append(F.CfgF(f'place={pl} cancel={cd}', fv_thr=0.08, **k))
    O.main(sys.argv[1].split(','), cfgs)
