"""latprobe - measure the quote-update cycle from inside a pod.

THE gate for strat-openmm-5m: the sim is +0.25 c/sh at a ~100ms reaction,
-0.43 at 200ms and -0.92 at 400ms (at 400ms even the PAIR component collapses,
+$922 -> -$74).  So we must know the real numbers before committing capital.

Measures, on a LIVE 5m market:
  sign_ms    EIP-712 signing (CPU, ~100-300ms) - must be PRESIGNED off the
             critical path; the strategy needs only ~8 placements/bar/coin so
             the whole .44-.56 band (13 px x 2 tokens) can be signed in advance
  post_ms    GTC post-only placement round trip   (the critical path)
  cancel_ms  cancel round trip                    (the critical path)
  cycle_ms   cancel+place = one re-pin            <= 150ms REQUIRED

SAFETY: places 5-share (venue orderMinSize) GTC post-only BUYs at a price far
below the touch so they cannot fill (max exposure ~$0.10/order), and cancels
each one immediately.  Aborts the whole run if any probe order reports a fill.

Usage (in-pod):  PM_LIVE=1 python3 tools/latprobe.py [--n 25] [--coin btc]
"""
import argparse
import asyncio
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

PROBE_PX = 0.02          # far below any mid-band touch => cannot fill
PROBE_SH = 5.0           # venue orderMinSize


def p90(v):
    if not v:
        return float('nan')
    if len(v) < 10:
        return max(v)
    return st.quantiles(v, n=10)[8]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=25)
    ap.add_argument('--coin', default='btc')
    ap.add_argument('--token', default=None,
                    help='token id to probe; default resolves the current 5m UP token')
    a = ap.parse_args()

    if os.environ.get('PM_LIVE') != '1':
        print('refusing to run: set PM_LIVE=1 (the probe must post REAL orders '
              'to measure anything meaningful)')
        return 2

    from execution.fastclient import FastExec

    token = a.token
    if token is None:
        from core import gamma
        for fn in ('current_market', 'market_for', 'bar_market', 'live_market'):
            f = getattr(gamma, fn, None)
            if f is None:
                continue
            try:
                mk = f(a.coin)
            except Exception:
                continue
            if mk:
                token = mk.get('up') if isinstance(mk, dict) else mk[0]
                break
    if not token:
        print('could not resolve the current 5m market; pass --token explicitly',
              file=sys.stderr)
        return 3

    print(f'probing {a.coin} token {str(token)[:18]}...  n={a.n} '
          f'px={PROBE_PX} size={PROBE_SH} (max exposure ~${PROBE_PX*PROBE_SH:.2f}/order)')

    fx = FastExec(live=True)
    fx.start()
    await fx.prewarm([token])

    sign, post, cancel, cycle = [], [], [], []
    for i in range(a.n):
        oid, matched, sms, pms, avg, filled = await fx.fire_direct(
            token, PROBE_PX, PROBE_SH)
        if matched or filled:
            print(f'ABORT: probe order FILLED (avg={avg} filled={filled}) - '
                  f'price {PROBE_PX} was not safe. Order id: {oid}')
            return 4
        sign.append(sms)
        post.append(pms)
        t1 = time.time()
        ok = await fx.cancel(oid)
        cms = (time.time() - t1) * 1000.0
        cancel.append(cms)
        cycle.append(pms + cms)
        if not ok:
            print(f'  [{i}] WARNING cancel returned False for {oid}')
        await asyncio.sleep(0.4)

    def row(name, v, budget=None):
        flag = ''
        if budget is not None:
            flag = '   <= BUDGET OK' if p90(v) <= budget else '   !! OVER BUDGET'
        print(f'  {name:10s} n={len(v):3d}  median {st.median(v):7.1f}ms  '
              f'p90 {p90(v):7.1f}ms  max {max(v):7.1f}ms{flag}')

    print(f'\n=== latency, {a.coin}, {a.n} probes ===')
    row('sign', sign)
    row('post', post)
    row('cancel', cancel)
    row('CYCLE', cycle, budget=150.0)
    print('\nverdict: strat-openmm-5m needs a re-pin CYCLE <=150ms '
          '(sim: 100ms=+0.25 c/sh, 200ms=-0.43, 400ms=-0.92).')
    print('note: sign_ms is OFF the critical path if the .44-.56 band is '
          'presigned during the previous bar (~8 placements/bar needed).')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
