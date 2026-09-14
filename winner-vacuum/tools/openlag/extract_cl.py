#!/usr/bin/env python3
"""cl-era extractor (data >= 2026-08-22, rows carry cl/cl_ts/tw).

Per bar emits:
  - strike_cl: mean of deduped 1Hz cl ticks in [ws-62, ws-3] (the real strike)
  - final_cl : mean over [end-62, end-3] (settlement recon)
  - margin_full (bps), margin_T2 (using only ticks ARRIVED by end+2s), tick counts
  - m0 vs strike_cl at open (spot proxy + cl point), sigma1m (bps, prior 60m spot)
  - pre/pre3 next1 quotes (as extract_open) + first-touch post-open deltas 2/5/10s
  - post-close: per side, first time each ask threshold was touched in [T, T+90]
    (dt + ask + size), and BUY-print share/notional sums per price bucket [T,T+120]
  - win (RES)
Usage: extract_cl.py <coin> <mrec_dir> <out_csv>
"""
import sys, os, re, gzip, glob
from collections import deque

coin, mdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
THR = [0.99, 0.95, 0.90, 0.75, 0.55, 0.30]
PB  = [(0.0,0.30),(0.30,0.55),(0.55,0.90),(0.90,0.99),(0.99,1.01)]
DELTAS = [2,5,10]

# tolerate optional whitespace after the colon. NOTE 2026-09-15: an agent reported
# this as a live defect ("btc writes '"t": 1789', bnb writes '"t":1789'"); it did
# NOT reproduce — all 7 coins are compact today and this regex matched 500/500 lines
# on every one. Kept tolerant as cheap insurance, since the vacmaker event log DOES
# use '", "' spacing and these parsers get copy-pasted between streams.
r_t   = re.compile(r'"t":\s*([0-9.]+)')
r_ws  = re.compile(r'"ws":([0-9]+)')
r_tl  = re.compile(r'"tl":(-?[0-9.]+)')
r_spot= re.compile(r'"spot":([0-9.eE+-]+)')
r_cl  = re.compile(r'"cl":([0-9.eE+-]+)')
r_clts= re.compile(r'"cl_ts":([0-9]+)')
r_ua  = re.compile(r'"ua":([0-9.]+|null)')
r_ub  = re.compile(r'"ub":([0-9.]+|null)')
r_da  = re.compile(r'"da":([0-9.]+|null)')
r_db  = re.compile(r'"db":([0-9.]+|null)')
r_uas = re.compile(r'"uas":([0-9.]+|null)')
r_das = re.compile(r'"das":([0-9.]+|null)')
r_win = re.compile(r'"win":"(UP|DOWN)"')
r_trd = re.compile(r'"trd":(\[\[.*\]\])')

def fnum(rx, line):
    m = rx.search(line)
    if not m: return None
    v = m.group(1)
    return None if v == 'null' else float(v)

cl_ticks = {}          # cl_ts -> (cl, first_arrival_t)
spot_sec = deque()     # (sec, spot) 1Hz-ish for sigma
bars = {}

def bar(ws):
    b = bars.get(ws)
    if b is None:
        b = bars[ws] = {'win':None,'pre':None,'pre3':None,'spot_open':None,
                        'cl_open':None,'sigma1m':None,'snaps':{},
                        'ft':{}, 'prints':{}, 'pseen':set(), 'post_seen':False}
    return b

def cl_window_stats(lo, hi, arrive_by=None):
    vals=[]
    for ts in range(int(lo), int(hi)+1):
        v = cl_ticks.get(ts)
        if v is None: continue
        if arrive_by is not None and v[1] > arrive_by: continue
        vals.append(v[0])
    if not vals: return None, 0
    return sum(vals)/len(vals), len(vals)

import math
def sigma1m(now):
    # std of 60s log-returns over the past hour, in bps
    pts = [p for p in spot_sec if p[0] >= now-3600]
    if len(pts) < 300: return None
    bys = {}
    for s,v in pts: bys[int(s)] = v
    ks = sorted(bys)
    rets=[]
    for k in ks:
        k2 = k+60
        if k2 in bys and bys[k]>0:
            rets.append(math.log(bys[k2]/bys[k])*1e4)
    if len(rets) < 30: return None
    mu = sum(rets)/len(rets)
    return (sum((r-mu)**2 for r in rets)/len(rets))**0.5

FIELDS = ['ws','win','strike_cl','nstrike','final_cl','nfinal','margin_full',
          'margin_T2','nT2','spot_open','cl_open','m0','sigma1m']
for d in DELTAS: FIELDS += [f'{p}{d}' for p in ('ua','ub','da','db')]
FIELDS += ['pre_t','pre_ua','pre_da','pre_uas','pre_das',
           'pre3_t','pre3_ua','pre3_da','pre3_uas','pre3_das']
for side in ('U','D'):
    for thr in THR: FIELDS += [f'ft_{side}_{int(thr*100)}_dt', f'ft_{side}_{int(thr*100)}_sz']
for side in ('U','D'):
    for i,(lo,hi) in enumerate(PB):
        for ag in ('B','S'):
            FIELDS += [f'pr_{side}_{i}_{ag}_sh', f'pr_{side}_{i}_{ag}_usd']

rows_out=[]
def finalize(ws):
    b = bars.pop(ws, None)
    if b is None or b['win'] is None: return
    end = ws+300
    sk, ns = cl_window_stats(ws-62, ws-3)
    fn, nf = cl_window_stats(end-62, end-3)
    m2, n2 = cl_window_stats(end-62, end-3, arrive_by=end+2.0)
    if sk is None or fn is None: return
    row = {'ws':ws,'win':b['win'],'strike_cl':round(sk,6),'nstrike':ns,
           'final_cl':round(fn,6),'nfinal':nf,
           'margin_full':round((fn/sk-1)*1e4,3),
           'margin_T2':round((m2/sk-1)*1e4,3) if m2 else None,'nT2':n2,
           'spot_open':b['spot_open'],'cl_open':b['cl_open'],
           'm0':round((b['spot_open']/sk-1)*1e4,3) if b['spot_open'] else None,
           'sigma1m':round(b['sigma1m'],2) if b['sigma1m'] else None}
    for d in DELTAS:
        s=b['snaps'].get(d) or {}
        for p in ('ua','ub','da','db'): row[f'{p}{d}']=s.get(p)
    for tag in ('pre','pre3'):
        p=b[tag] or {}
        row[f'{tag}_t']=p.get('t')
        for k in ('ua','da','uas','das'): row[f'{tag}_{k}']=p.get(k)
    for side in ('U','D'):
        for thr in THR:
            v=b['ft'].get((side,thr))
            row[f'ft_{side}_{int(thr*100)}_dt']= round(v[0],2) if v else None
            row[f'ft_{side}_{int(thr*100)}_sz']= v[1] if v else None
    for side in ('U','D'):
        for i,_ in enumerate(PB):
            for ag in ('B','S'):
                v=b['prints'].get((side,i,ag),(0.0,0.0))
                row[f'pr_{side}_{i}_{ag}_sh']=round(v[0],1); row[f'pr_{side}_{i}_{ag}_usd']=round(v[1],2)
    rows_out.append(row)

files = sorted(glob.glob(os.path.join(mdir, coin, f'{coin}-mrec-2026082[2-9]*.jsonl.gz')) +
               sorted(glob.glob(os.path.join(mdir, coin, f'{coin}-mrec-202609*.jsonl.gz'))))
maxt=0
last_sec=None
for fp in files:
    try:
        with gzip.open(fp,'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    m=r_win.search(line); w=r_ws.search(line)
                    if m and w: bar(int(w.group(1)))['win']=m.group(1)
                    continue
                if '"ev":"SNAP"' not in line: continue
                t=fnum(r_t,line)
                if t is None: continue
                if t>maxt: maxt=t
                cts=r_clts.search(line)
                if cts:
                    ts=int(cts.group(1)); clv=fnum(r_cl,line)
                    if clv and ts not in cl_ticks: cl_ticks[ts]=(clv,t)
                role_cur='"role":"cur"' in line
                role_n1 ='"role":"next1"' in line
                role_post='"role":"post"' in line
                w=r_ws.search(line)
                if not w: continue
                ws=int(w.group(1))
                tl=fnum(r_tl,line)
                if tl is None: continue
                if role_cur:
                    spot=fnum(r_spot,line)
                    sec=int(t)
                    if spot and sec!=last_sec:
                        spot_sec.append((sec,spot)); last_sec=sec
                        while spot_sec and spot_sec[0][0]<sec-3700: spot_sec.popleft()
                    dt=300.0-tl
                    if 0<=dt<=12:
                        b=bar(ws)
                        if b['spot_open'] is None and spot and dt<=2.0:
                            b['spot_open']=spot
                            b['cl_open']=fnum(r_cl,line)
                            b['sigma1m']=sigma1m(t)
                        for d in DELTAS:
                            if dt>=d and d not in b['snaps']:
                                b['snaps'][d]={'ua':fnum(r_ua,line),'ub':fnum(r_ub,line),
                                               'da':fnum(r_da,line),'db':fnum(r_db,line)}
                elif role_n1:
                    if tl<=300: continue
                    b=bar(ws)
                    rec={'tl':tl,'t':round(300-tl,1),'ua':fnum(r_ua,line),'da':fnum(r_da,line),
                         'uas':fnum(r_uas,line),'das':fnum(r_das,line)}
                    pre=b['pre']
                    if pre is None or tl<pre['tl']: b['pre']=rec
                    if tl>=303.0:
                        p3=b['pre3']
                        if p3 is None or tl<p3['tl']: b['pre3']=rec
                elif role_post:
                    dt=-tl   # seconds after close
                    if dt<0 or dt>130: continue
                    b=bar(ws)
                    ua=fnum(r_ua,line); da=fnum(r_da,line)
                    uas=fnum(r_uas,line); das=fnum(r_das,line)
                    if dt<=90:
                        for side,ask,sz in (('U',ua,uas),('D',da,das)):
                            if ask is None: continue
                            for thr in THR:
                                if ask<=thr and (side,thr) not in b['ft']:
                                    b['ft'][(side,thr)]=(dt,sz)
                    mtr=r_trd.search(line)
                    if mtr:
                        try:
                            import json
                            for tr in json.loads(mtr.group(1)):
                                ts_,tok,px,sz,sd = tr[0],tr[1],float(tr[2]),float(tr[3]),tr[4]
                                ag='B' if sd=='BUY' else 'S'
                                dtp=ts_-(ws+300)
                                if dtp<0 or dtp>120: continue
                                dk=(ts_,tok,px,sz)
                                if dk in b['pseen']: continue
                                b['pseen'].add(dk)
                                key=(tok, next(i for i,(lo,hi) in enumerate(PB) if lo<=px<hi), ag)
                                s=b['prints'].get(key,(0.0,0.0))
                                b['prints'][key]=(s[0]+sz, s[1]+sz*px)
                        except StopIteration: pass
                        except Exception: pass
    except (EOFError,OSError) as e:
        print(f'WARN {fp}: {e}', file=sys.stderr)
    for ws in [x for x in list(bars) if x < maxt-1200]:
        finalize(ws)
    # trim cl_ticks
    for ts in [x for x in list(cl_ticks) if x < maxt-7200]: del cl_ticks[ts]

for ws in sorted(list(bars)): finalize(ws)
import csv
with open(out,'w',newline='') as f:
    wtr=csv.DictWriter(f,fieldnames=FIELDS); wtr.writeheader()
    for r in sorted(rows_out,key=lambda x:x['ws']): wtr.writerow(r)
print(f'{coin}: {len(rows_out)} bars -> {out}')
