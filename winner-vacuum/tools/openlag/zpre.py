#!/usr/bin/env python3
"""z-normalized pre-open seam on archive eras.
sigma5m per bar = std of last 12 strike-to-strike log-returns (bps).
z = m0/sigma5m. Era-correct strikes."""
import csv, glob, time, math
from collections import defaultdict
E30_LO=time.mktime(time.strptime('2026-08-07','%Y-%m-%d'))-time.timezone
E30_HI=time.mktime(time.strptime('2026-08-14','%Y-%m-%d'))-time.timezone
E60_LO=time.mktime(time.strptime('2026-08-15','%Y-%m-%d'))-time.timezone
def g(r,k):
    v=r.get(k,'')
    return float(v) if v not in ('','None') else None
ZB=[(0.7,1.2),(1.2,2.0),(2.0,3.5),(3.5,1e9)]
st=defaultdict(lambda:defaultdict(lambda:[0,0,0.0,0.0]))
coin_st=defaultdict(lambda:[0,0,0.0])
dd=defaultdict(lambda:[0,0,0.0])
clus=defaultdict(list)
for fp in sorted(glob.glob('*_open.csv')):
    coin=fp.split('_')[0]
    if coin=='test': continue
    rows=list(csv.DictReader(open(fp)))
    hist=[]  # (ws, strike-era-correct)
    for r in rows:
        ws=int(r['ws'])
        if E30_LO<=ws<E30_HI: era='t30'; sk=g(r,'strike30')
        elif ws>=E60_LO: era='t60'; sk=g(r,'strike')
        else: era='pt'; sk=g(r,'strike')
        if not sk: continue
        # sigma from trailing 12 strike diffs (only consecutive bars)
        hist.append((ws,sk))
        if len(hist)>14: hist.pop(0)
        rets=[math.log(hist[i][1]/hist[i-1][1])*1e4 for i in range(1,len(hist))
              if hist[i][0]-hist[i-1][0]==300]
        if len(rets)<8: continue
        mu=sum(rets)/len(rets)
        sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
        if sig<=0: continue
        so=g(r,'spot_open'); win=r['win']
        if not so or win not in ('UP','DOWN') or era=='pt': continue
        m0=(so/sk-1)*1e4; z=m0/sig; az=abs(z)
        if az<0.7: continue
        side='UP' if z>0 else 'DOWN'
        ask=g(r,'pre3_ua') if side=='UP' else g(r,'pre3_da')
        if ask is None or ask<=0 or ask>=1: continue
        fee=0.07*ask*(1-ask); won=1 if win==side else 0; ev=won-ask-fee
        for lo,hi in ZB:
            if lo<=az<hi: st[era][(lo,hi)][0]+=1; st[era][(lo,hi)][1]+=won; st[era][(lo,hi)][2]+=ask; st[era][(lo,hi)][3]+=ev
        if az>=1.2:
            coin_st[(era,coin)][0]+=1; coin_st[(era,coin)][1]+=won; coin_st[(era,coin)][2]+=ev
            day=time.strftime('%m-%d',time.gmtime(ws))
            dd[(era,day)][0]+=1; dd[(era,day)][1]+=won; dd[(era,day)][2]+=ev
            clus[ws].append(ev)
for era in ('t30','t60'):
    print(f'== {era} (pre3, z-normalized) ==')
    for b in ZB:
        n,w,sa,sev=st[era][b]
        if n<8: continue
        lbl=f'{b[0]}-{b[1] if b[1]<1e8 else "inf"}'
        print(f'  |z| {lbl:>8}: n={n:4d} win {100*w/n:5.1f}% avgask {sa/n:.3f} EV/sh {100*sev/n:+6.2f}c')
print('\nper-coin |z|>=1.2:')
for k in sorted(coin_st):
    n,w,ev=coin_st[k]
    print(f'  {k[0]}/{k[1]}: n={n:3d} win {100*w/n:5.1f}% EV {ev:+6.2f}')
print('\nday split |z|>=1.2:')
for k in sorted(dd):
    n,w,ev=dd[k]
    print(f'  {k[0]}/{k[1]}: n={n:3d} win {100*w/n:5.1f}% EV {ev:+6.2f}')
cm=[sum(v)/len(v) for v in clus.values()]
print(f'\nclusters(ws) |z|>=1.2: {len(cm)}, mean {100*sum(cm)/max(len(cm),1):+.2f}c/sh, positive {sum(1 for x in cm if x>0)}/{len(cm)}')
