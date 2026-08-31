#!/usr/bin/env python3
"""Pre-open MAKER economics census (cl-era, last 60s before open).
Maker PnL: BUY print -> maker sold at px: pnl/sh = px - won(tok)
           SELL print -> maker bought at px: pnl/sh = won(tok) - px
(Makers pay no fee.)"""
import csv, glob, time, collections
def band(px):
    for lo,hi,name in [(0,0.3,'<0.30'),(0.3,0.45,'0.30-45'),(0.45,0.55,'0.45-55'),
                       (0.55,0.72,'0.55-72'),(0.72,0.9,'0.72-90'),(0.9,1.01,'>0.90')]:
        if lo<=px<hi: return name
def zb(z):
    if z is None: return 'z?'
    az=abs(z)
    if az<0.5: return 'z<0.5'
    if az<1.2: return 'z0.5-1.2'
    return 'z>=1.2'
tot=collections.defaultdict(lambda:[0.0,0.0,0])   # key->(pnl$, notional$, prints)
days=collections.defaultdict(float)
coins=collections.defaultdict(float)
allpnl=0.0; allnot=0.0; npr=0
for fp in sorted(glob.glob('*_premm.csv')):
    coin=fp.split('_')[0]
    for r in csv.DictReader(open(fp)):
        px=float(r['px']); sz=float(r['sz']); tok=r['tok']; win=r['win']
        z=float(r['z']) if r['z'] not in ('','None') else None
        tbo=float(r['tbo']); sd=r['sd']
        won=1.0 if (tok=='U')==(win=='UP') else 0.0
        pnl=(px-won)*sz if sd=='BUY' else (won-px)*sz
        notion=px*sz
        allpnl+=pnl; allnot+=notion; npr+=1
        day=time.strftime('%m-%d',time.gmtime(int(r['ws'])))
        days[day]+=pnl; coins[coin]+=pnl
        tb='0-3s' if tbo<3 else ('3-10s' if tbo<10 else '10-60s')
        for k in [('px',band(px)),('tbo',tb),('z',zb(z)),('sd',sd),
                  ('cell', (zb(z),band(px)) if tbo<10 else None)]:
            if k[1] is not None: 
                t=tot[k]; t[0]+=pnl; t[1]+=notion; t[2]+=1
print(f'ALL pre-open prints (last 60s, 8d, 7 coins): n={npr}, maker notional ${allnot:,.0f}, MAKER PnL ${allpnl:+,.0f} ({100*allpnl/allnot:+.2f}% of notional, ${allpnl/8:+.0f}/day)')
print('\nby price band:')
for k in sorted([k for k in tot if k[0]=='px'], key=lambda x:x[1]):
    p,n,c=tot[k]; print(f'  {k[1]:>8}: prints {c:6d} notional ${n:9,.0f} maker ${p:+8,.0f} ({100*p/max(n,1):+.2f}%)')
print('by seconds-before-open:')
for k in [('tbo','0-3s'),('tbo','3-10s'),('tbo','10-60s')]:
    p,n,c=tot[k]; print(f'  {k[1]:>7}: prints {c:6d} notional ${n:9,.0f} maker ${p:+8,.0f} ({100*p/max(n,1):+.2f}%)')
print('by |z|:')
for k in sorted([k for k in tot if k[0]=='z'], key=lambda x:x[1]):
    p,n,c=tot[k]; print(f'  {k[1]:>9}: prints {c:6d} notional ${n:9,.0f} maker ${p:+8,.0f} ({100*p/max(n,1):+.2f}%)')
print('by aggressor:')
for k in [('sd','BUY'),('sd','SELL')]:
    p,n,c=tot[k]; print(f'  taker-{k[1]:>4}: prints {c:6d} notional ${n:9,.0f} maker ${p:+8,.0f} ({100*p/max(n,1):+.2f}%)')
print('\nthe openlag cell (tbo<10s), z x px:')
for k in sorted([k for k in tot if k[0]=='cell'], key=lambda x:str(x[1])):
    p,n,c=tot[k]
    if c>=30: print(f'  {str(k[1]):>24}: prints {c:5d} notional ${n:8,.0f} maker ${p:+7,.0f} ({100*p/max(n,1):+.2f}%)')
print('\nby day:', ' '.join(f'{k}:{v:+.0f}' for k,v in sorted(days.items())))
print('by coin:', ' '.join(f'{k}:{v:+.0f}' for k,v in sorted(coins.items())))
