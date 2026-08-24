import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imbmm as I, fvmm as F, openmm2 as O
O.BarSim = I.ImbBar
if __name__ == '__main__':
    cfgs = []
    for thr in (0.2, 0.4):
        k = dict(F.BEST); k['delay'] = 0.2
        cfgs.append(I.CfgI(f'imb>={thr} d0.2', fv_thr=0.08, imb_thr=thr, **k))
        cfgs.append(I.CfgI(f'imb>={thr} d0.2 RAND', fv_thr=0.08, imb_thr=thr,
                           rand=True, **k))
    k = dict(F.BEST); k['delay'] = 0.2
    cfgs.append(I.CfgI('nogate d0.2 (ctrl)', fv_thr=0.08, imb_thr=None, **k))
    O.main(sys.argv[1].split(','), cfgs)
