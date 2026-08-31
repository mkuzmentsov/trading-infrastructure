#!/usr/bin/env python3
"""Day/coin robustness of the LATE (tbo<10s) pre-open maker slice."""
import csv, glob, time, collections
days=collections.defaultdict(lambda:[0.0,0.0]); coins=collections.defaultdict(lambda:[0.0,0.0])
d03=collections.defaultdict(lambda:[0.0,0.0])
zcell=collections.defaultdict(lambda:[0.0,0.0])
for fp in sorted(glob.glob('*_premm.csv')):
    coin=fp.split('_')[0]
    for r in csv.DictReader(open(fp)):
        tbo=float(r['tbo'])
        if tbo>=10: continue
        px=float(r['px']); sz=float(r['sz']); tok=r['tok']; win=r['win']; sd=r['sd']
        won=1.0 if (tok=='U')==(win=='UP') else 0.0
        pnl=(px-won)*sz if sd=='BUY' else (won-px)*sz
        day=time.strftime('%m-%d',time.gmtime(int(r['ws'])))
        days[day][0]+=pnl; days[day][1]+=px*sz
        coins[coin][0]+=pnl; coins[coin][1]+=px*sz
        if tbo<3: d03[day][0]+=pnl; d03[day][1]+=px*sz
        z=float(r['z']) if r['z'] not in ('','None') else None
        if z is not None and abs(z)>=0.5:
            zcell[day][0]+=pnl; zcell[day][1]+=px*sz
print('LATE slice (tbo<10s) maker PnL by day:')
for k in sorted(days):
    p,n=days[k]; p3,n3=d03[k]
    print(f'  {k}: 0-10s ${p:+7.0f} ({100*p/max(n,1):+.2f}% of ${n:,.0f})   0-3s ${p3:+6.0f} ({100*p3/max(n3,1):+.2f}%)')
print('by coin (0-10s):')
for k in sorted(coins):
    p,n=coins[k]; print(f'  {k:5}: ${p:+7.0f} ({100*p/max(n,1):+.2f}% of ${n:,.0f})')
print('|z|>=0.5 subset (0-10s) by day:')
for k in sorted(zcell):
    p,n=zcell[k]; print(f'  {k}: ${p:+7.0f} ({100*p/max(n,1):+.2f}% of ${n:,.0f})')
