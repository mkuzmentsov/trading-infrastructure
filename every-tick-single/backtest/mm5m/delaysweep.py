"""THE decisive test: is mid-price 5m making a latency race we could win?

The field's at-touch makers re-price inside ~100ms.  Sweep our reaction delay
from 50ms to 800ms on the touch-tracking quoter.  If the sign flips somewhere
we can reach (our pods: Helsinki -> PM CLOB ~Frankfurt, FAST_EXEC presigned),
there is a strategy; if it is negative even at 50ms, passive mid-price making
is structurally dead for us at any achievable speed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deepmm as D
import openmm2 as O

if __name__ == '__main__':
    coins = sys.argv[1].split(',') if len(sys.argv) > 1 else ['btc']
    cfgs = []
    for d in (0.05, 0.1, 0.2, 0.4, 0.8):
        cfgs.append(D.Cfg2(f'touch delay={d}', offset=0, repin=True, delay=d))
    for d in (0.05, 0.1):
        cfgs.append(D.Cfg2(f'touch d={d} +pull.25', offset=0, repin=True, delay=d,
                           pull_bps=0.25, pull_win=1.0))
    cfgs.append(D.Cfg2('touch d=0.05 RAND', offset=0, repin=True, delay=0.05, rand=True))
    O.main(coins, cfgs)
