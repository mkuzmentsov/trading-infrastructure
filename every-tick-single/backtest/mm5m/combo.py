import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deepmm as D, openmm2 as O

BEST = dict(offset=0, repin=True, delay=0.1, pull_bps=0.1, pull_win=0.5)
if __name__ == '__main__':
    coins = sys.argv[1].split(',')
    mode = sys.argv[2]
    if mode == 'combo':
        cfgs = []
        for lo, hi in ((240, 297), (45, 297), (120, 297)):
            for b in ((0.44, 0.56), (0.40, 0.60), (0.46, 0.54)):
                cfgs.append(D.Cfg2(f'tl{lo}-{hi} b{b[0]}-{b[1]}', tl_lo=lo, tl_hi=hi, band=b, **BEST))
    elif mode == 'coin':
        cfgs = [D.Cfg2('b.44-.56 open', tl_lo=240, tl_hi=297, band=(.44, .56), **BEST),
                D.Cfg2('b.44-.56 full', tl_lo=45,  tl_hi=297, band=(.44, .56), **BEST),
                D.Cfg2('b.40-.60 full', tl_lo=45,  tl_hi=297, band=(.40, .60), **BEST),
                D.Cfg2('RAND ctrl',     tl_lo=45,  tl_hi=297, band=(.44, .56), rand=True, **BEST)]
    O.main(coins, cfgs)
