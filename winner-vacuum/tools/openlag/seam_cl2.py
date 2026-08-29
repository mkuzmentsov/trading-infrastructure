#!/usr/bin/env python3
"""Basis-clean OOS variants:
A: m0 from cl_open (pure Chainlink, relay-delayed but basis-free)
B: m0 from spot with rolling-median basis removed (fresh + basis-corrected)
Also: ask-conditional slice (stale-book subset ask<=0.62), and per-variant null.
"""
import csv, glob, time, math, random, collections
random.seed(11)
def g(r,k):
    v=r.get(k,'')
    return float(v) if v not in ('','None',None) else None
ZB=[(0.7,1.2),(1.2,2.0),(2.0,3.5),(3.5,1e9)]
def run(variant):
    st=collections.defaultdict(lambda:[0,0,0.0,0.0])
    dd=collections.defaultdict(lambda:[0,0,0.0])
    trig=[]; pool=collections.defaultdict(list)
    for fp in sorted(glob.glob('*_cl.csv')):
        coin=fp.split('_')[0]
        hist=[]; basis=collections.deque(maxlen=36)
        for r in csv.DictReader(open(fp)):
            ws=int(r['ws']); sk=g(r,'strike_cl'); ns=g(r,'nstrike') or 0
            win=r['win']
            if not sk or ns<40 or win not in ('UP','DOWN'): continue
            hist.append((ws,sk))
            if len(hist)>14: hist.pop(0)
            for side,askk in (('UP','pre3_ua'),('DOWN','pre3_da')):
                a=g(r,askk)
                if a and 0<a<1: pool[round(a/0.02)].append(1 if win==side else 0)
            so=g(r,'spot_open'); co=g(r,'cl_open')
            if so and sk: basis.append((so/sk-1)*1e4 if False else (so and co and (so/co-1)*1e4) or 0)
            rets=[math.log(hist[i][1]/hist[i-1][1])*1e4 for i in range(1,len(hist)) if hist[i][0]-hist[i-1][0]==300]
            if len(rets)<8: continue
            mu=sum(rets)/len(rets); sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
            if sig<=0: continue
            if variant=='A':
                if not co: continue
                m0=(co/sk-1)*1e4
            else:
                if not so or len(basis)<12: continue
                bs=sorted(basis); bmed=bs[len(bs)//2]
                m0=(so/sk-1)*1e4 - bmed
            z=m0/sig; az=abs(z)
            if az<0.7: continue
            side='UP' if z>0 else 'DOWN'
            ask=g(r,'pre3_ua') if side=='UP' else g(r,'pre3_da')
            if ask is None:
                ask=g(r,'pre_ua') if side=='UP' else g(r,'pre_da')
            if ask is None or ask<=0 or ask>=1: continue
            fee=0.07*ask*(1-ask); won=1 if win==side else 0; ev=won-ask-fee
            for lo,hi in ZB:
                if lo<=az<hi:
                    s=st[(lo,hi)]; s[0]+=1; s[1]+=won; s[2]+=ask; s[3]+=ev
            if az>=1.2:
                trig.append({'ask':ask,'won':won,'ev':ev,'st':round(ask/0.02),'ws':ws})
                day=time.strftime('%m-%d',time.gmtime(ws)); dd[day][0]+=1; dd[day][1]+=won; dd[day][2]+=ev
    print(f'== variant {variant} ==')
    for b in ZB:
        n,w,sa,sev=st[b]
        if n<5: continue
        lbl=f'{b[0]}-{b[1] if b[1]<1e8 else "inf"}'
        print(f'  |z| {lbl:>8}: n={n:4d} win {100*w/n:5.1f}% avgask {sa/n:.3f} EV/sh {100*sev/n:+6.2f}c')
    stale=[t for t in trig if t['ask']<=0.62]
    if stale:
        print(f'  |z|>=1.2 & ask<=0.62 (stale-book subset): n={len(stale)} win {100*sum(t["won"] for t in stale)/len(stale):.1f}% EV/sh {100*sum(t["ev"] for t in stale)/len(stale):+.2f}c')
    N=len(trig); EV=sum(t['ev'] for t in trig)
    if N>=10:
        null=[]
        for rep in range(2000):
            ev=0.0
            for t in trig:
                p=pool[t['st']]; w=random.choice(p) if p else t['won']
                ev+=w-t['ask']-0.07*t['ask']*(1-t['ask'])
            null.append(ev)
        null.sort(); mu=sum(null)/len(null); sd=(sum((x-mu)**2 for x in null)/len(null))**0.5 or 1
        print(f'  |z|>=1.2: n={N} EV {EV:+.2f} ({100*EV/N:+.2f}c/sh); null {mu:+.2f}±{sd:.2f} -> z={(EV-mu)/sd:+.2f} p={sum(1 for x in null if x>=EV)/len(null):.4f}')
    print('  days:', ' '.join(f'{k}:{v[2]:+.1f}' for k,v in sorted(dd.items())))
run('A'); run('B')
