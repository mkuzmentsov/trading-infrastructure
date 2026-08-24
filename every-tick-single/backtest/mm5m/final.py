import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O
if __name__ == '__main__':
    cfgs = []
    for sz in (25, 50):
        k = dict(F.BEST); k['size'] = sz
        cfgs.append(F.CfgF(f'FINAL size={sz}', fv_thr=0.08, **k))
    k = dict(F.BEST); k['size'] = 25
    cfgs.append(F.CfgF('RAND ctrl s=25', fv_thr=0.08, rand=True, **k))
    O.main(sys.argv[1].split(','), cfgs)
