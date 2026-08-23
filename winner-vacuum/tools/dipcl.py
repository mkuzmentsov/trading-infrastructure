"""dipcl — "buy the dip" on CHAINLINK ground truth (2026-08-23, §41).

Answers: if the recon says X wins and the book offers X cheap, is the MARKET
wrong or is the ESTIMATE wrong?  §38 could only ask this through the Binance
proxy (0.46 bps side error, worst exactly on the cheap = near-tie bars); the
recorders carry `cl`/`cl_ts`/`tw` since 2026-08-21 19:25 UTC, so this asks it
on the stream the market actually settles on.

USAGE
  1. pull the cl-era archives (read-only, per file, size-verified):
       for c in btc eth sol xrp bnb doge hype; do
         for f in $(kubectl exec -n every-tick-single deploy/$c-mrec-every-tick-single \
                    -- sh -c 'ls /app/logs/raw/*-2026082[123]-*.jsonl.gz'); do
           kubectl exec -n every-tick-single deploy/$c-mrec-every-tick-single -- cat "$f" \
             > "$DIR/$c/$(basename $f)"; done; done
       # verify: gzip -t (tar-over-exec truncates — ledger)
  2. python3 dipcl.py extract <dir>      # -> <dir>/x2_<coin>.pkl
  3. python3 dipcl.py sim <dir>

MODEL: strike = the TWAP tick stamped at ws (`tw`); the settlement value is the
mean of the 60 cl ticks in [T-62, T-3]; at decision time we know only the ticks
the RELAY had delivered (the row's own `cl_ts` — this bakes in the 2.2s relay
delay instead of assuming clairvoyance), the rest persist at the last tick.
One clip per bar, at the FIRST qualifying instant, so events are independent.

CONTROLS (all three must hold or the run is void):
  V1 reconstructed-TWAP side == venue RES on ~99.5% of bars
  V2 the live-config replica lands on the live fleet's ROI
  V3 side-flipped placebo is catastrophically negative

⚠️ READ §41 BEFORE BELIEVING THE CHEAP CELLS. This sim assumes a displayed ask
is takeable. Live it is not: at ask<=0.75 the FAK fills 11% of the time and the
fills are the WRONG ones (71% side-correct vs 100% on the bars we never filled).
Cheap-band ROI here is ~7x the live number for that reason.
"""
import gzip, json, glob, os, pickle, sys, collections, datetime as dt
from math import comb

COINS = ['btc', 'eth', 'sol', 'xrp', 'bnb', 'doge', 'hype']
CLIP = 8.0


def extract(SC):
    for coin in COINS:
        out = f'{SC}/x2_{coin}.pkl'
        if os.path.exists(out):
            print('skip', coin); continue
        CL, TW, SP, res = {}, {}, {}, {}
        books = collections.defaultdict(dict)
        for f in sorted(glob.glob(f'{SC}/cl/{coin}/*.jsonl.gz')):
            with gzip.open(f, 'rt') as fh:
                for l in fh:
                    if '"RES"' in l:
                        d = json.loads(l); res[d['ws']] = d['win']; continue
                    if '"SNAP"' not in l:
                        continue
                    d = json.loads(l)
                    ct = d.get('cl_ts')
                    if ct:
                        ct = int(ct)
                        if d.get('cl'):
                            CL[ct] = d['cl']
                        if d.get('tw'):
                            TW[ct] = d['tw']
                    if d.get('spot'):
                        SP[int(d['t'])] = d['spot']
                    if d.get('role') != 'cur':
                        continue
                    tl = d.get('tl')
                    if tl is None or not (2 <= tl <= 45):
                        continue
                    # the tick VISIBLE at this instant (ct) is what a live
                    # decision could have used — never the tick stamped at it
                    books[d['ws']][int(tl)] = (d.get('ua'), d.get('uas'), d.get('da'),
                                               d.get('das'), d.get('ub'), d.get('db'),
                                               ct, d.get('t'))
        pickle.dump(dict(CL=CL, TW=TW, SP=SP, res=res, books=dict(books)), open(out, 'wb'), 2)
        print(coin, 'bars', len(books), 'res', len(res), 'cl', len(CL), flush=True)


def load(SC):
    BARS, v1, skip = [], [0, 0], collections.Counter()
    for coin in COINS:
        D = pickle.load(open(f'{SC}/x2_{coin}.pkl', 'rb'))
        CL, TW, res, books = D['CL'], D['TW'], D['res'], D['books']
        for ws, bk in sorted(books.items()):
            if ws not in res:
                skip['nores'] += 1; continue
            T = ws + 300
            strike = next((TW[s] for s in range(ws, ws - 4, -1) if s in TW), None)
            if strike is None:
                skip['nostrike'] += 1; continue
            w = [CL[s] for s in range(T - 62, T - 2) if s in CL]
            if len(w) < 55:
                skip['thin'] += 1; continue
            truth = sum(w) / len(w)
            v1[0] += 1; v1[1] += (('UP' if truth >= strike else 'DOWN') == res[ws])
            pts = {}
            for tl, b in bk.items():
                if not (3 <= tl <= 30):
                    continue
                ua, uas, da, das, ub, db, ct, trow = b
                if not ct:
                    continue
                kn = [CL[s] for s in range(T - 62, min(ct + 1, T - 2)) if s in CL]
                if len(kn) < 10:
                    continue
                est = (sum(kn) + (60 - len(kn)) * kn[-1]) / 60
                m = (est - strike) / strike * 1e4
                side = 'UP' if m > 0 else 'DOWN'
                ask, sz = (ua, uas) if side == 'UP' else (da, das)
                pts[tl] = (m, side, ask, sz or 0.0)
            BARS.append((coin, ws, dt.datetime.utcfromtimestamp(ws).strftime('%m-%d'),
                         pts, res[ws]))
    print('bars=%d  V1 reconstructed-TWAP side == venue RES: %d/%d = %.2f%%  skipped=%s'
          % (len(BARS), v1[1], v1[0], 100 * v1[1] / max(v1[0], 1), dict(skip)))
    return BARS


def run(BARS, gate, lo, hi, tlmax=20, minsz=5.0, flip=False, slope=0.0):
    out = []
    for coin, ws, d, pts, won in BARS:
        for tl in sorted((t for t in pts if 3 <= t <= tlmax), reverse=True):
            m, side, ask, sz = pts[tl]
            if abs(m) < gate + slope * max(0, tl - 14) or not ask \
               or not (lo < ask <= hi) or sz < minsz:
                continue
            sh = min(CLIP, sz)
            w = (won == side) if not flip else (won != side)
            out.append((coin, d, tl, ask, m, w, sh * ((1 - ask) if w else -ask), sh * ask, sh))
            break
    return out


def line(tag, o):
    if not o:
        print('  %-26s  (no events)' % tag); return
    n = len(o); w = sum(x[5] for x in o)
    p = sum(x[6] for x in o); c = sum(x[7] for x in o); sh = sum(x[8] for x in o)
    be = c / sh
    pv = sum(comb(n, k) * be ** k * (1 - be) ** (n - k) for k in range(w, n + 1))
    print('  %-26s n=%4d win=%5.1f%% b/e=%5.1f%%  pnl=%+8.2f staked=%8.2f roi=%+7.2f%%  P(binom)=%.4f'
          % (tag, n, 100 * w / n, 100 * be, p, c, 100 * p / c, pv))


BANDS = [('0.02-0.10', .02, .10), ('0.10-0.25', .10, .25), ('0.25-0.40', .25, .40),
         ('0.40-0.55', .40, .55), ('0.55-0.75', .55, .75), ('0.75-0.90', .75, .90),
         ('0.90-0.95', .90, .95), ('0.95-0.98', .95, .98), ('0.98-1.00', .98, 1.0)]


def sim(SC):
    BARS = load(SC)
    for gate in (1.0, 3.0, 5.0):
        print('\n===== GATE >= %.1f bps, one clip/bar at the first qualifying tl<=20 =====' % gate)
        for nm, lo, hi in BANDS:
            line(nm, run(BARS, gate, lo, hi))
    print('\n===== V2 CONTROL: the LIVE config (ask .55-.98, 0.5+0.035*(tl-14), tl<=20) =====')
    line('live-config replica', run(BARS, 0.5, 0.55, 0.98, slope=0.035))
    print('\n===== V3 PLACEBO (side flipped) =====')
    line('placebo', run(BARS, 3.0, 0.25, 0.90, flip=True))
    print('\n===== candidate cell per day / per coin: gate>=3bps, ask 0.25-0.90, tl<=20 =====')
    o = run(BARS, 3.0, 0.25, 0.90)
    line('ALL', o)
    for key, idx in (('day', 1), ('coin', 0)):
        agg = collections.defaultdict(list)
        for x in o:
            agg[x[idx]].append(x)
        for k in sorted(agg):
            line('  %s=%s' % (key, k), agg[k])


if __name__ == '__main__':
    (extract if sys.argv[1] == 'extract' else sim)(sys.argv[2])
