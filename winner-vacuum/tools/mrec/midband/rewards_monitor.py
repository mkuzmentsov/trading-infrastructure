#!/usr/bin/env python3
"""Rewards-return monitor for 5m crypto up/down markets (agent C, 2026-09-07).
Polls gamma for the CURRENT 5m bar of each coin and reports the liquidity-rewards fields.
A non-empty `clobRewards` with rewardsDailyRate>0 on any 5m market = a rewards program is back
(Aug-2026 shape).  Run ad hoc or from cron:  python3 rewards_monitor.py [--loop SECS]
Exit code 2 when rewards are detected (so a cron/alert can key on it).  Not deployed.
"""
import json, sys, time, urllib.request
COINS=['btc','eth','sol','xrp','bnb','doge','hype','zec']
UA={'User-Agent':'Mozilla/5.0 (rewards-monitor)'}
def gamma(slug):
    req=urllib.request.Request(f'https://gamma-api.polymarket.com/markets?slug={slug}',headers=UA)
    return json.load(urllib.request.urlopen(req,timeout=20))
def check():
    now=int(time.time()); found=[]
    for c in COINS:
        m=None
        for off in (0,-300,300,-600):
            ws=now-(now%300)+off
            try: d=gamma(f'{c}-updown-5m-{ws}')
            except Exception as e: continue
            if d and not d[0].get('closed'): m=d[0]; break
        if not m: print(f'{c:5s} no current market found'); continue
        rw=m.get('clobRewards') or []
        rate=sum(float(r.get('rewardsDailyRate') or 0) for r in rw)
        fs=m.get('feeSchedule') or {}
        print(f"{c:5s} {m['slug']:28s} minSize={m.get('rewardsMinSize')} maxSpread={m.get('rewardsMaxSpread')} "
              f"dailyRate=${rate:.2f} rebateRate={fs.get('rebateRate')} takerRate={fs.get('rate')} tick={m.get('orderPriceMinTickSize')}")
        if rate>0: found.append((c,rate,m.get('rewardsMaxSpread')))
    return found
if __name__=='__main__':
    loop=int(sys.argv[sys.argv.index('--loop')+1]) if '--loop' in sys.argv else 0
    while True:
        f=check()
        if f:
            print('*** REWARDS DETECTED ***',f)
            if not loop: sys.exit(2)
        if not loop: sys.exit(0)
        time.sleep(loop)
