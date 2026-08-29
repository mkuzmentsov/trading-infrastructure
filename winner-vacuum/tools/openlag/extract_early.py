#!/usr/bin/env python3
"""Earlier-fire probe: at t0 = ws-10 and ws-30, record (a) the last next1 book
quote at/before t0, (b) partial strike = mean cl ticks in [ws-62,ws-3] ARRIVED
by t0, (c) latest arrived cl value at t0 (the live price view), (d) sigma5m
built from full strikes (lookahead-free: previous bars only). Labels from RES.
Usage: extract_early.py <coin> <mrec_dir> <out_csv>"""
import sys, os, re, gzip, glob, math

coin, mdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
r_t=re.compile(r'"t":([0-9.]+)'); r_ws=re.compile(r'"ws":([0-9]+)')
r_tl=re.compile(r'"tl":(-?[0-9.]+)')
r_cl=re.compile(r'"cl":([0-9.eE+-]+)'); r_clts=re.compile(r'"cl_ts":([0-9]+)')
r_ua=re.compile(r'"ua":([0-9.]+|null)'); r_da=re.compile(r'"da":([0-9.]+|null)')
r_win=re.compile(r'"win":"(UP|DOWN)"')
def fnum(rx,l):
    m=rx.search(l)
    if not m: return None
    v=m.group(1)
    return None if v=='null' else float(v)
cl_ticks={}
bars={}
T0S=[10,30]
def bar(ws):
    b=bars.get(ws)
    if b is None: b=bars[ws]={'win':None,'q':{}}
    return b
def pstrike(ws,t0abs):
    vals=[]; last=None; lastts=None
    for ts in range(ws-62,ws-2):
        v=cl_ticks.get(ts)
        if v and v[1]<=t0abs: vals.append(v[0])
    # latest arrived tick anywhere before t0
    for ts in range(int(t0abs)+2,int(t0abs)-40,-1):
        v=cl_ticks.get(ts)
        if v and v[1]<=t0abs: last=v[0]; lastts=ts; break
    return (sum(vals)/len(vals) if vals else None), len(vals), last, lastts
rows=[]
FIELDS=['ws','win','strike_full']
for d in T0S: FIELDS+=[f'ps{d}',f'nps{d}',f'cl{d}',f'ua{d}',f'da{d}']
def finalize(ws):
    b=bars.pop(ws,None)
    if b is None or b['win'] is None: return
    vals=[cl_ticks[ts][0] for ts in range(ws-62,ws-2) if ts in cl_ticks]
    if len(vals)<40: return
    row={'ws':ws,'win':b['win'],'strike_full':round(sum(vals)/len(vals),6)}
    for d in T0S:
        q=b['q'].get(d) or {}
        ps,nps,last,_=pstrike(ws,ws-d)
        row[f'ps{d}']=round(ps,6) if ps else None
        row[f'nps{d}']=nps
        row[f'cl{d}']=round(last,6) if last else None
        row[f'ua{d}']=q.get('ua'); row[f'da{d}']=q.get('da')
    rows.append(row)
files=sorted(glob.glob(os.path.join(mdir,coin,f'{coin}-mrec-2026082[2-9]*.jsonl.gz')))
maxt=0
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
                if '"role":"next1"' not in line: continue
                w=r_ws.search(line); tl=fnum(r_tl,line)
                if not w or tl is None or tl<=300: continue
                ws=int(w.group(1)); b=bar(ws)
                for d in T0S:
                    if tl>=300+d:
                        cur=b['q'].get(d)
                        if cur is None or tl<cur['tl']:
                            b['q'][d]={'tl':tl,'ua':fnum(r_ua,line),'da':fnum(r_da,line)}
    except (EOFError,OSError) as e:
        print(f'WARN {fp}: {e}',file=sys.stderr)
    for ws in [x for x in list(bars) if x<maxt-1200]: finalize(ws)
    for ts in [x for x in list(cl_ticks) if x<maxt-7200]: del cl_ticks[ts]
for ws in sorted(list(bars)): finalize(ws)
import csv
with open(out,'w',newline='') as f:
    wtr=csv.DictWriter(f,fieldnames=FIELDS); wtr.writeheader()
    for r in sorted(rows,key=lambda x:x['ws']): wtr.writerow(r)
print(f'{coin}: {len(rows)} bars -> {out}')
