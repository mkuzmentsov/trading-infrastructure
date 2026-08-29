#!/usr/bin/env python3
"""Earlier-fire seam test at ws-10 / ws-30: signal = latest-arrived cl vs
PARTIAL strike (arrived ticks), z vs sigma5m from prior full strikes."""
import csv, glob, time, math, random, collections
random.seed(11)
def g(r,k):
    v=r.get(k,'')
    return float(v) if v not in ('','None',None) else None
for D in (10,30):
    trig=[]; pool=collections.defaultdict(list)
    st=collections.defaultdict(lambda:[0,0,0.0,0.0])
    for fp in sorted(glob.glob('*_early.csv')):
        coin=fp.split('_')[0]
        hist=[]
        for r in csv.DictReader(open(fp)):
            ws=int(r['ws']); sf=g(r,'strike_full'); win=r['win']
            if not sf or win not in ('UP','DOWN'): continue
            # sigma from PRIOR bars only (hist excludes current until after use)
            rets=[math.log(hist[i][1]/hist[i-1][1])*1e4 for i in range(1,len(hist)) if hist[i][0]-hist[i-1][0]==300]
            ok_sig=len(rets)>=8
            if ok_sig:
                mu=sum(rets)/len(rets); sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
            hist.append((ws,sf))
            if len(hist)>14: hist.pop(0)
            for side,askk in (('UP',f'ua{D}'),('DOWN',f'da{D}')):
                a=g(r,askk)
                if a and 0<a<1: pool[round(a/0.02)].append(1 if win==side else 0)
            if not ok_sig or sig<=0: continue
            ps=g(r,f'ps{D}'); nps=g(r,f'nps{D}') or 0; cl=g(r,f'cl{D}')
            if not ps or not cl or nps<20: continue
            z=(cl/ps-1)*1e4/sig; az=abs(z)
            if az<0.7: continue
            side='UP' if z>0 else 'DOWN'
            ask=g(r,f'ua{D}') if side=='UP' else g(r,f'da{D}')
            if ask is None or ask<=0 or ask>=1: continue
            fee=0.07*ask*(1-ask); won=1 if win==side else 0; ev=won-ask-fee
            ZB=[(0.7,1.2),(1.2,2.0),(2.0,1e9)]
            for lo,hi in ZB:
                if lo<=az<hi:
                    s=st[(lo,hi)]; s[0]+=1; s[1]+=won; s[2]+=ask; s[3]+=ev
            if az>=1.2:
                trig.append({'ask':ask,'won':won,'ev':ev,'st':round(ask/0.02),
                             'day':time.strftime('%m-%d',time.gmtime(ws)),'ws':ws})
    print(f'== fire at ws-{D} ==')
    for b in [(0.7,1.2),(1.2,2.0),(2.0,1e9)]:
        n,w,sa,sev=st[b]
        if n<5: continue
        print(f'  |z| {b[0]}-{b[1] if b[1]<1e8 else "inf"}: n={n:4d} win {100*w/n:5.1f}% avgask {sa/n:.3f} EV/sh {100*sev/n:+6.2f}c')
    N=len(trig)
    if N>=10:
        EV=sum(t['ev'] for t in trig)
        null=[]
        for rep in range(2000):
            ev=0.0
            for t in trig:
                p=pool[t['st']]; w=random.choice(p) if p else t['won']
                ev+=w-t['ask']-0.07*t['ask']*(1-t['ask'])
            null.append(ev)
        null.sort(); mu=sum(null)/len(null); sd=(sum((x-mu)**2 for x in null)/len(null))**0.5 or 1
        dd=collections.defaultdict(float)
        for t in trig: dd[t['day']]+=t['ev']
        print(f'  |z|>=1.2: n={N} EV {EV:+.2f} ({100*EV/N:+.2f}c/sh) null z={(EV-mu)/sd:+.2f} p={sum(1 for x in null if x>=EV)/len(null):.4f}')
        print('  days:', ' '.join(f'{k}:{v:+.1f}' for k,v in sorted(dd.items())))
