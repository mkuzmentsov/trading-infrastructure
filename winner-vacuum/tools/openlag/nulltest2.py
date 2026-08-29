#!/usr/bin/env python3
"""Correct null: for each trigger, draw outcome from the ALL-BAR-SIDES pool
at the same pre3-ask stratum (preserves P(win|ask), destroys z info)."""
import csv, glob, time, math, random, collections
random.seed(11)
E30_LO=time.mktime(time.strptime('2026-08-07','%Y-%m-%d'))-time.timezone
E30_HI=time.mktime(time.strptime('2026-08-14','%Y-%m-%d'))-time.timezone
E60_LO=time.mktime(time.strptime('2026-08-15','%Y-%m-%d'))-time.timezone
def g(r,k):
    v=r.get(k,'')
    return float(v) if v not in ('','None') else None
trig=[]; pool=collections.defaultdict(list)
for fp in sorted(glob.glob('*_open.csv')):
    coin=fp.split('_')[0]
    if coin=='test': continue
    hist=[]
    for r in csv.DictReader(open(fp)):
        ws=int(r['ws'])
        era_ok = (E30_LO<=ws<E30_HI) or (ws>=E60_LO)
        sk=g(r,'strike30') if (E30_LO<=ws<E30_HI) else g(r,'strike')
        if not sk: continue
        hist.append((ws,sk))
        if len(hist)>14: hist.pop(0)
        win=r['win']
        if win not in ('UP','DOWN'): continue
        # pool: both sides with asks (era-valid only)
        if era_ok:
            for side,askk in (('UP','pre3_ua'),('DOWN','pre3_da')):
                a=g(r,askk)
                if a and 0<a<1:
                    pool[round(a/0.02)].append(1 if win==side else 0)
        if not era_ok: continue
        rets=[math.log(hist[i][1]/hist[i-1][1])*1e4 for i in range(1,len(hist)) if hist[i][0]-hist[i-1][0]==300]
        if len(rets)<8: continue
        mu=sum(rets)/len(rets); sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
        if sig<=0: continue
        so=g(r,'spot_open')
        if not so: continue
        z=(so/sk-1)*1e4/sig
        if abs(z)<1.2: continue
        side='UP' if z>0 else 'DOWN'
        ask=g(r,'pre3_ua') if side=='UP' else g(r,'pre3_da')
        if ask is None or ask<=0 or ask>=1: continue
        fee=0.07*ask*(1-ask); won=1 if win==side else 0
        trig.append({'ws':ws,'ask':ask,'fee':fee,'won':won,'ev':won-ask-fee,'st':round(ask/0.02)})
N=len(trig); EV=sum(t['ev'] for t in trig)
print(f'triggers {N}, EV {EV:+.2f} ({100*EV/N:+.2f}c/sh)')
for st in sorted(set(t['st'] for t in trig)):
    p=pool[st]
    tt=[t for t in trig if t['st']==st]
    if len(tt)>=8:
        print(f'  ask~{st*0.02:.2f}: triggers {len(tt)} win {100*sum(t["won"] for t in tt)/len(tt):.0f}% vs pool base {100*sum(p)/max(len(p),1):.0f}% (pool n={len(p)})')
null=[]
for rep in range(4000):
    ev=0.0
    for t in trig:
        p=pool[t['st']]
        w=random.choice(p) if p else t['won']
        ev+=w-t['ask']-t['fee']
    null.append(ev)
null.sort()
mu=sum(null)/len(null); sd=(sum((x-mu)**2 for x in null)/len(null))**0.5
p=sum(1 for x in null if x>=EV)/len(null)
print(f'null: mean {mu:+.2f} sd {sd:.2f}; observed {EV:+.2f}; z={(EV-mu)/sd:+.2f}; p={p:.4f}')
