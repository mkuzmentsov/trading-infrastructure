import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imbmm as I, fvmm as F, openmm2 as O
O.BarSim = I.ImbBar
if __name__ == '__main__':
    cfgs = []
    for dly in (0.2, 0.4):
        k = dict(F.BEST); k['delay'] = dly
        cfgs.append(I.CfgI(f'imb>=0.2 d{dly}', fv_thr=0.08, imb_thr=0.2, **k))
        cfgs.append(I.CfgI(f'imb>=0.2 d{dly} RAND', fv_thr=0.08, imb_thr=0.2,
                           rand=True, **k))
    k = dict(F.BEST); k['delay'] = 0.2; k['size'] = 25
    cfgs.append(I.CfgI('imb>=0.2 d0.2 sz25', fv_thr=0.08, imb_thr=0.2, **k))
    O.main(sys.argv[1].split(','), cfgs)
