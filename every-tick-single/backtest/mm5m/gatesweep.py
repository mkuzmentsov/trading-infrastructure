"""Tune the spot-pull gate at the achievable reaction speed (1 snapshot = 100ms).
The pull is our only defence against the fair value moving under a resting quote:
PM 5m price moves ~4.4c per bps of BTC, so sub-bps spot drift is the whole risk."""
import sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deepmm as D
import openmm2 as O

if __name__ == '__main__':
    coins = sys.argv[1].split(',') if len(sys.argv) > 1 else ['btc']
    which = sys.argv[2] if len(sys.argv) > 2 else 'pull'
    if which == 'pull':
        cfgs = [D.Cfg2('no pull', offset=0, repin=True, delay=0.1)]
        for p, w in itertools.product((0.1, 0.2, 0.3, 0.5), (0.5, 1.0, 2.0)):
            cfgs.append(D.Cfg2(f'pull {p}bps/{w}s', offset=0, repin=True, delay=0.1,
                               pull_bps=p, pull_win=w))
    elif which == 'win':
        cfgs = []
        for lo, hi in ((240, 297), (210, 297), (150, 297), (240, 290), (255, 295), (270, 297), (45, 297)):
            cfgs.append(D.Cfg2(f'tl {lo}-{hi}', offset=0, repin=True, delay=0.1,
                               pull_bps=0.1, pull_win=0.5, tl_lo=lo, tl_hi=hi))
    elif which == 'band':
        cfgs = []
        for b in ((0.30, 0.70), (0.40, 0.60), (0.44, 0.56), (0.46, 0.70), (0.30, 0.56)):
            cfgs.append(D.Cfg2(f'band {b}', offset=0, repin=True, delay=0.1,
                               pull_bps=0.1, pull_win=0.5, band=b))
    O.main(coins, cfgs)
