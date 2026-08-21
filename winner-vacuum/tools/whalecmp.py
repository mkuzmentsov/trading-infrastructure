#!/usr/bin/env python3
"""Compare our whale-clone fills vs 0xefdf6abc over the last N hours.
Runs IN a pod (needs data-api + /app/logs). Usage: whalecmp.py [hours]"""
import json,glob,gzip,sys,time,urllib.request,collections,re
HOURS=float(sys.argv[1]) if len(sys.argv)>1 else 2.0
SINCE=time.time()-HOURS*3600
H={'User-Agent':'Mozilla/5.0'}
W='0xefdf6abc3ef35f93c2753c4d36f3e17fdfb87ea5'
rows=[]
for off in (0,500):
    try:
        r=json.load(urllib.request.urlopen(urllib.request.Request(
            'https://data-api.polymarket.com/activity?user=%s&limit=500&offset=%d&type=TRADE'%(W,off),headers=H)))
        rows+=r
        if len(r)<500: break
    except Exception as e:
        print('whale fetch err',str(e)[:60]); break
his=collections.defaultdict(list)
for t in rows:
    if t.get('timestamp',0)<SINCE or t.get('side')!='BUY': continue
    m=re.search(r'([a-z]+)-updown-5m-(\d+)',t.get('slug',''))
    if m: his[(m.group(1),int(m.group(2)))].append((float(t['price']),float(t.get('size',0))))
ours=collections.defaultdict(list)
coin=None
for f in glob.glob('/app/logs/logs-training-events.jsonl'):
    for l in open(f):
        try: d=json.loads(l)
        except: continue
        if d.get('t',0)<SINCE: continue
        if d.get('ev') in ('PF_TE_WHALE_ORDER','PF_TE_LIVE_ORDER') and d.get('filled'):
            coin=d.get('coin')
            ours[(d['coin'],d['bar'])].append((d.get('avg_px') or 0,d.get('filled')))
        if d.get('ev')=='PF_TE_MAKER_REST' and (d.get('crossed') or 0)>0:
            coin=d.get('coin')
            ours[(d['coin'],d['bar'])].append((d.get('crossed_avg') or 0,d.get('crossed')))
bars=sorted(set([k for k in his if coin and k[0]==coin])|set(ours))
print(f'=== {coin or "?"} last {HOURS:.0f}h — HIM vs US (bar: clips@px) ===')
both=onlyhim=onlyus=0
for c,b in bars:
    if coin and c!=coin: continue
    h=his.get((c,b),[]); o=ours.get((c,b),[])
    tag='BOTH' if h and o else ('HIM ' if h else ' US ')
    if h and o: both+=1
    elif h: onlyhim+=1
    else: onlyus+=1
    hs=','.join(f'{p:.2f}' for p,_ in h) or '-'
    os_=','.join(f'{p:.2f}' for p,_ in o) or '-'
    print(f'{tag} {time.strftime("%H:%M",time.gmtime(b))} him[{len(h)}: {hs}] us[{len(o)}: {os_}]')
print(f'summary: both={both} him-only={onlyhim} us-only={onlyus}')
