#!/usr/bin/env python3
"""Score 0xefdf6abc's 5m trades against ACTUAL resolution.

The question this answers: on the bars we skip but he takes, does he MAKE money?
If not, the gap is a feature and closing it is -EV (leaderboard lesson, 2x proven).
Usage: whalepnl.py [hours]   -- runs anywhere with data-api + gamma reachable.
"""
import json, sys, time, urllib.request, collections, re

HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 72.0
SINCE = time.time() - HOURS * 3600
H = {'User-Agent': 'Mozilla/5.0'}
W = sys.argv[2] if len(sys.argv) > 2 else '0xefdf6abc3ef35f93c2753c4d36f3e17fdfb87ea5'

def get(u):
    for _ in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30))
        except Exception: time.sleep(1.5)
    return []

# ── his trades ────────────────────────────────────────────────────────────
rows, off = [], 0
while off < 6000:
    r = get(f'https://data-api.polymarket.com/activity?user={W}&limit=500&offset={off}&type=TRADE')
    if not r: break
    rows += r
    if len(r) < 500 or min(t.get('timestamp', 0) for t in r) < SINCE: break
    off += 500

# key = (conditionId, outcomeIndex); BUY adds, SELL removes
pos = collections.defaultdict(lambda: {'sh': 0.0, 'cost': 0.0, 'n': 0})
meta = {}
for t in rows:
    if t.get('timestamp', 0) < SINCE: continue
    m = re.match(r'([a-z]+)-updown-5m-(\d+)$', t.get('slug', ''))
    if not m: continue
    cid, oi = t['conditionId'], t['outcomeIndex']
    sz, px = float(t['size']), float(t['price'])
    p = pos[(cid, oi)]
    if t['side'] == 'BUY': p['sh'] += sz; p['cost'] += sz * px; p['n'] += 1
    else:                  p['sh'] -= sz; p['cost'] -= sz * px
    meta[cid] = (m.group(1), int(m.group(2)))

# ── resolution (gamma, batched) ───────────────────────────────────────────
cids = sorted({c for c, _ in pos})
res = {}
for i in range(0, len(cids), 20):
    q = '&'.join(f'condition_ids={c}' for c in cids[i:i+20])
    for mk in get(f'https://gamma-api.polymarket.com/markets?{q}&closed=true') or []:
        try: op = json.loads(mk['outcomePrices'])
        except Exception: continue
        res[mk['conditionId']] = [float(x) for x in op]

# ── per-bar PnL ───────────────────────────────────────────────────────────
bars = collections.defaultdict(lambda: {'pnl': 0.0, 'stake': 0.0, 'clips': 0, 'px': []})
unres = 0
for (cid, oi), p in pos.items():
    if p['sh'] <= 1e-9: continue
    r = res.get(cid)
    if not r: unres += 1; continue
    payout = p['sh'] * r[oi]
    b = bars[meta[cid]]
    b['pnl'] += payout - p['cost']; b['stake'] += p['cost']; b['clips'] += p['n']
    if p['sh']: b['px'].append(p['cost'] / p['sh'])

tot = sum(b['pnl'] for b in bars.values()); stake = sum(b['stake'] for b in bars.values())
wins = sum(1 for b in bars.values() if b['pnl'] > 0); n = len(bars)
print(f'=== {W[:10]} — last {HOURS:.0f}h ===')
print(f'bars={n}  clips={sum(b["clips"] for b in bars.values())}  unresolved-skipped={unres}')
print(f'staked=${stake:,.0f}  PnL=${tot:+,.2f}  ROI={tot/stake*100 if stake else 0:+.2f}%  winbars={wins}/{n} ({wins/n*100 if n else 0:.0f}%)')

print('\n-- by entry price bucket (his edge lives at the CHEAP end) --')
buck = collections.defaultdict(lambda: [0, 0.0, 0.0])
for b in bars.values():
    if not b['px']: continue
    a = sum(b['px']) / len(b['px'])
    k = '<0.80' if a < .80 else '0.80-0.94' if a < .94 else '0.94-0.98' if a < .98 else '>=0.98'
    buck[k][0] += 1; buck[k][1] += b['pnl']; buck[k][2] += b['stake']
for k in ('<0.80', '0.80-0.94', '0.94-0.98', '>=0.98'):
    c, pl, st = buck[k]
    if c: print(f'  {k:>10}  bars={c:4d}  PnL=${pl:+9.2f}  ROI={pl/st*100 if st else 0:+7.2f}%')

print('\n-- by coin --')
per = collections.defaultdict(lambda: [0, 0.0, 0.0])
for (c, _), b in bars.items():
    per[c][0] += 1; per[c][1] += b['pnl']; per[c][2] += b['stake']
for c, (k, pl, st) in sorted(per.items(), key=lambda x: -x[1][1]):
    print(f'  {c:>5}  bars={k:4d}  PnL=${pl:+9.2f}  ROI={pl/st*100 if st else 0:+7.2f}%')

json.dump({f'{c}|{b}': v for (c, b), v in bars.items()}, open(sys.argv[3] if len(sys.argv)>3 else '/tmp/whale_bars.json','w'))
print('\nper-bar detail -> /tmp/whale_bars.json')
