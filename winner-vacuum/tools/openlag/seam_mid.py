#!/usr/bin/env python3
"""Battery on the moderate-z slice (cl-era, pre3, sigma5m from strike_cl):
z5m in [0.45,1.2) — the band where section-3 suggested residual EV."""
import csv, glob, time, math, random, collections
random.seed(11)
def g(r,k):
    v=r.get(k,'')
    return float(v) if v not in ('','None',None) else None
trig=[]; pool=collections.defaultdict(list)
for fp in sorted(glob.glob('*_cl.csv')):
    coin=fp.split('_')[0]
    hist=[]
    for r in csv.DictReader(open(fp)):
        ws=int(r['ws']); sk=g(r,'strike_cl'); ns=g(r,'nstrike') or 0
        win=r['win']
        if not sk or ns<40 or win not in ('UP','DOWN'): continue
        hist.append((ws,sk))
        if len(hist)>14: hist.pop(0)
        for side,askk in (('UP','pre3_ua'),('DOWN','pre3_da')):
            a=g(r,askk)
            if a and 0<a<1: pool[round(a/0.02)].append(1 if win==side else 0)
        co=g(r,'cl_open')
        rets=[math.log(hist[i][1]/hist[i-1][1])*1e4 for i in range(1,len(hist)) if hist[i][0]-hist[i-1][0]==300]
        if len(rets)<8 or not co: continue
        mu=sum(rets)/len(rets); sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
        if sig<=0: continue
        z=(co/sk-1)*1e4/sig; az=abs(z)
        if not (0.45<=az<1.2): continue
        side='UP' if z>0 else 'DOWN'
        ask=g(r,'pre3_ua') if side=='UP' else g(r,'pre3_da')
        if ask is None or ask<=0 or ask>=1: continue
        fee=0.07*ask*(1-ask); won=1 if win==side else 0
        trig.append({'ws':ws,'coin':coin,'ask':ask,'won':won,'ev':won-ask-fee,'st':round(ask/0.02),
                     'day':time.strftime('%m-%d',time.gmtime(ws))})
N=len(trig); EV=sum(t['ev'] for t in trig)
print(f'z5m [0.45,1.2) cl-open signal: n={N}, win {100*sum(t["won"] for t in trig)/N:.1f}%, avgask {sum(t["ask"] for t in trig)/N:.3f}, EV {EV:+.2f} ({100*EV/N:+.2f}c/sh)')
dd=collections.defaultdict(lambda:[0,0.0])
for t in trig: dd[t['day']][0]+=1; dd[t['day']][1]+=t['ev']
print('days:', ' '.join(f'{k}:n{v[0]}:{v[1]:+.1f}' for k,v in sorted(dd.items())))
cc=collections.defaultdict(lambda:[0,0.0])
for t in trig: cc[t['coin']][0]+=1; cc[t['coin']][1]+=t['ev']
print('coins:', ' '.join(f'{k}:n{v[0]}:{v[1]:+.1f}' for k,v in sorted(cc.items())))
clus=collections.defaultdict(list)
for t in trig: clus[t['ws']].append(t['ev'])
cm=[sum(v)/len(v) for v in clus.values()]
print(f'clusters {len(cm)}, mean {100*sum(cm)/len(cm):+.2f}c, pos {sum(1 for x in cm if x>0)}/{len(cm)}')
null=[]
for rep in range(2000):
    ev=0.0
    for t in trig:
        p=pool[t['st']]; w=random.choice(p) if p else t['won']
        ev+=w-t['ask']-0.07*t['ask']*(1-t['ask'])
    null.append(ev)
null.sort(); mu=sum(null)/len(null); sd=(sum((x-mu)**2 for x in null)/len(null))**0.5 or 1
print(f'stratified null: {mu:+.2f}±{sd:.2f} -> z={(EV-mu)/sd:+.2f}, p={sum(1 for x in null if x>=EV)/len(null):.4f}')
# ask-level cut
ab=collections.defaultdict(lambda:[0,0,0.0])
for t in trig:
    b=round(int(t['ask']*10)/10,1); ab[b][0]+=1; ab[b][1]+=t['won']; ab[b][2]+=t['ev']
for k in sorted(ab):
    n,w,ev=ab[k]
    if n>=20: print(f'  ask {k:.1f}x: n={n:4d} win {100*w/n:5.1f}% EV/sh {100*ev/n:+6.2f}c')
