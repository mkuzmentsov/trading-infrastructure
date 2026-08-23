r"""fillphys — LIVE fill physics of the vacmaker's FAK clips (2026-08-23, §41).

The offline sims assume a displayed ask is takeable. This measures what the
venue actually did with our orders, from the pods' own event logs:

  1. match rate by seen ask band      (does a cheap ask fill at all?)
  2. ADVERSE SELECTION, per bar       (were the fills the right ones?)
     -> bars where we filled cheap vs bars where we hammered and never filled
  3. PnL/ROI by ask band x tl band    (what the cheap lane actually earns)

Pull the logs first (read-only):
  for c in btc eth sol xrp bnb doge hype; do
    kubectl exec -n every-tick-single deploy/$c-vacmaker-every-tick-single -- \
      cat /app/logs/logs-training-events.jsonl > $DIR/$c.jsonl
    for f in $(kubectl exec -n every-tick-single deploy/$c-vacmaker-every-tick-single -- \
               sh -c 'ls /app/logs/logs-training-events.jsonl.*.gz'); do
      kubectl exec -n every-tick-single deploy/$c-vacmaker-every-tick-single -- cat "$f" \
        > "$DIR/$c.$(basename $f | sed 's/.*jsonl\.//')"; done; done

Usage: python3 fillphys.py <dir-with-the-logs>
"""
import json, glob, gzip, collections, sys
from math import comb

D = sys.argv[1]
orders, obar, settles, won = [], collections.defaultdict(list), [], {}
for f in sorted(glob.glob(f'{D}/*')):
    op = gzip.open if f.endswith('.gz') else open
    coin = f.split('/')[-1].split('.')[0]
    for l in op(f, 'rt'):
        try:
            d = json.loads(l)
        except Exception:
            continue
        e = d.get('ev')
        if e == 'PF_TE_WHALE_ORDER':
            orders.append((coin, d)); obar[(coin, d['bar'])].append(d)
        elif e == 'PF_TE_LIVE_SETTLE':
            settles.append((coin, d)); won[(coin, d['bar'])] = d['won']
        elif e == 'PF_TE_SETTLE' and d.get('won'):
            won.setdefault((coin, d['bar']), d['won'])

BAND = lambda a: ('<=0.55' if a <= .55 else '0.55-0.75' if a <= .75 else '0.75-0.90' if a <= .90
                  else '0.90-0.95' if a <= .95 else '0.95-0.98' if a <= .98 else '>0.98')
TLB = lambda t: 'unk' if t is None else '<=12' if t <= 12 else '13-20' if t <= 20 else \
                '21-30' if t <= 30 else '>30'
ORDER = ('<=0.55', '0.55-0.75', '0.75-0.90', '0.90-0.95', '0.95-0.98', '>0.98')

print('=== 1. FAK match rate by seen ask (n=%d orders sent) ===' % len(orders))
agg = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
for coin, d in orders:
    a = d.get('seen_ask')
    if not a:
        continue
    g = agg[BAND(a)]; g[0] += 1; g[3] += d.get('req_sh') or 0
    if d.get('matched'):
        g[1] += 1; g[2] += d.get('filled') or 0
for b in ORDER:
    n, m, f, r = agg[b]
    if n:
        print('  %-11s sent=%5d matched=%5d = %5.1f%%   shares %6.1f/%7.1f = %.1f%%'
              % (b, n, m, 100 * m / n, f, r, 100 * f / max(r, 1)))

print('\n=== 2. ADVERSE SELECTION (per bar): did the intended side win? ===')
agg = collections.defaultdict(lambda: [0, 0, 0])
for k, ds in obar.items():
    w = won.get(k)
    if not w:
        continue
    cheap = [d for d in ds if (d.get('seen_ask') or 1) <= 0.90]
    if not cheap:
        continue
    lo = min(d['seen_ask'] for d in cheap)
    g = agg[('<=0.75' if lo <= .75 else '0.75-0.90',
             'FILLED' if any(d.get('matched') for d in cheap) else 'NEVER')]
    g[0] += 1; g[1] += (w == cheap[0]['side']); g[2] += len(cheap)
for b in ('<=0.75', '0.75-0.90'):
    for s in ('FILLED', 'NEVER'):
        n, w, t = agg[(b, s)]
        if n:
            print('  %-10s %-7s bars=%4d side-correct=%5.1f%%   attempts/bar=%.1f'
                  % (b, s, n, 100 * w / n, t / n))

print('\n=== 3. settled clips by ask band x tl ===')
omap = {(c, d['bar'], d.get('clip')): d for c, d in orders if d.get('matched')}
agg = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
for coin, d in settles:
    px = d.get('avg_px') or 0
    if not px:
        continue
    o = omap.get((coin, d['bar'], d.get('clip')))
    g = agg[(BAND(px), TLB(o['tl'] if o else None))]
    g[0] += 1; g[1] += d['side'] == d['won']; g[2] += d.get('pnl', 0.0)
    g[3] += d.get('cost') or 0; g[4] += d.get('filled') or 0
print('  ask band     tl        n   win%    b/e%     PnL$   staked$     ROI%')
tot = [0, 0, 0.0, 0.0, 0.0]
for b in ORDER:
    for t in ('<=12', '13-20', '21-30', '>30', 'unk'):
        n, w, p, c, sh = agg[(b, t)]
        if not n:
            continue
        print('  %-11s %-6s %5d  %5.1f%%  %5.1f%%  %+8.2f  %8.2f  %+7.2f%%'
              % (b, t, n, 100 * w / n, 100 * c / sh if sh else 0, p, c, 100 * p / c if c else 0))
        for i in range(5):
            tot[i] += [n, w, p, c, sh][i]
print('  TOTAL n=%d win=%.1f%% pnl=%+.2f staked=%.2f roi=%+.2f%%'
      % (tot[0], 100 * tot[1] / max(tot[0], 1), tot[2], tot[3], 100 * tot[2] / max(tot[3], 1e-9)))

print('\n=== 4. the cheap lane (ask .55-.90, tl<=20): robustness ===')
sel = []
for coin, d in settles:
    px = d.get('avg_px') or 0
    o = omap.get((coin, d['bar'], d.get('clip')))
    if not px or not o or o['tl'] > 20 or not (.55 < px <= .90):
        continue
    sel.append((coin, d['side'] == d['won'], d.get('pnl', 0.0), d.get('cost') or 0,
                d.get('filled') or 0))
if sel:
    n = len(sel); w = sum(x[1] for x in sel)
    p = sum(x[2] for x in sel); c = sum(x[3] for x in sel); sh = sum(x[4] for x in sel)
    be = c / sh
    pv = sum(comb(n, k) * be ** k * (1 - be) ** (n - k) for k in range(w, n + 1))
    print('  n=%d win=%.1f%% breakeven=%.1f%% pnl=%+.2f staked=%.2f roi=%+.2f%% P(binom)=%.4f'
          % (n, 100 * w / n, 100 * be, p, c, 100 * p / c, pv))
