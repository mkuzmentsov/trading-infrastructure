"""Re-tune AT the measured venue latency (190ms median / 239ms p90 placement).
Params were tuned at 100ms; the honest test is whether ANY config survives 0.2-0.3s."""
import sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fvmm as F, openmm2 as O

if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    cfgs = []
    for dly in (0.2, 0.3):
        for band in ((0.44, 0.56), (0.40, 0.60), (0.46, 0.54)):
            for thr in (0.08, 0.03):
                k = dict(F.BEST); k['delay'] = dly; k['band'] = band
                cfgs.append(F.CfgF(f'd{dly} b{band[0]}-{band[1]} fv{thr}',
                                   fv_thr=thr, **k))
    O.main(coins, cfgs)
