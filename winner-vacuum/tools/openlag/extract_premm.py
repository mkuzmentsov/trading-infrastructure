#!/usr/bin/env python3
"""Pre-open MAKER census extractor (cl-era files).
Per bar: strike_cl (real), z (vs sigma5m from strike history), RES outcome,
and EVERY deduped pre-open print from next1 rows in [ws-60, ws):
(secs_before_open, token, px, sz, aggressor_side).
Maker PnL per BUY print = px - 1{token won}; per SELL print = 1{won} - px
(maker bought). Output: one prints CSV per coin.
Usage: extract_premm.py <coin> <mrec_dir> <out_csv>
"""
import sys, os, re, gzip, glob, json, math

coin, mdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
r_ws  = re.compile(r'"ws":([0-9]+)')
r_tl  = re.compile(r'"tl":(-?[0-9.]+)')
r_t   = re.compile(r'"t":([0-9.]+)')
r_cl  = re.compile(r'"cl":([0-9.eE+-]+)')
r_clts= re.compile(r'"cl_ts":([0-9]+)')
r_win = re.compile(r'"win":"(UP|DOWN)"')
r_trd = re.compile(r'"trd":(\[\[.*\]\])')

def fnum(rx,l):
    m=rx.search(l)
    if not m: return None
    v=m.group(1)
    return None if v=='null' else float(v)

cl_ticks={}
bars={}
def bar(ws):
    b=bars.get(ws)
    if b is None: b=bars[ws]={'win':None,'prints':[],'seen':set()}
    return b

def strike(ws):
    vals=[cl_ticks[ts] for ts in range(ws-62,ws-2) if ts in cl_ticks]
    return (sum(vals)/len(vals), len(vals)) if vals else (None,0)

rows=[]
strike_hist=[]
def finalize(ws):
    b=bars.pop(ws,None)
    if b is None or b['win'] is None: return
    sk,ns=strike(ws)
    if not sk or ns<40: return
    global strike_hist
    strike_hist.append((ws,sk))
    strike_hist=strike_hist[-14:]
    rets=[math.log(strike_hist[i][1]/strike_hist[i-1][1])*1e4
          for i in range(1,len(strike_hist))
          if strike_hist[i][0]-strike_hist[i-1][0]==300]
    sig=None
    if len(rets)>=8:
        mu=sum(rets)/len(rets)
        sig=(sum((x-mu)**2 for x in rets)/len(rets))**0.5
    # z at ws-3 (locked): last cl tick arrived-agnostic (census, not live replay)
    lastcl=None
    for ts in range(ws-3, ws-40, -1):
        if ts in cl_ticks: lastcl=cl_ticks[ts]; break
    z=None
    if lastcl and sig and sig>0: z=round((lastcl/sk-1)*1e4/sig,2)
    for tbo,tok,px,sz,sd in b['prints']:
        rows.append({'ws':ws,'win':b['win'],'z':z,'tbo':round(tbo,2),
                     'tok':tok,'px':px,'sz':sz,'sd':sd})

files=sorted(glob.glob(os.path.join(mdir,coin,f'{coin}-mrec-2026*.jsonl.gz')))
files=[f for f in files if '20260822' <= f.split('-mrec-')[1][:8]]
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
                if t and t>maxt: maxt=t
                cts=r_clts.search(line)
                if cts:
                    ts=int(cts.group(1)); v=fnum(r_cl,line)
                    if v and ts not in cl_ticks: cl_ticks[ts]=v
                if '"role":"next1"' not in line: continue
                w=r_ws.search(line); tl=fnum(r_tl,line)
                if not w or tl is None or tl<=300: continue
                ws=int(w.group(1))
                mtr=r_trd.search(line)
                if not mtr: continue
                try: trs=json.loads(mtr.group(1))
                except Exception: continue
                b=bar(ws)
                for tr in trs:
                    ts_,tok,px,sz,sd=tr[0],tr[1],float(tr[2]),float(tr[3]),tr[4]
                    tbo=ws-ts_
                    if tbo<0 or tbo>60: continue
                    dk=(ts_,tok,px,sz)
                    if dk in b['seen']: continue
                    b['seen'].add(dk)
                    b['prints'].append((tbo,tok,px,sz,sd))
    except (EOFError,OSError) as e:
        print(f'WARN {fp}: {e}',file=sys.stderr)
    for ws in sorted([x for x in list(bars) if x<maxt-1200]): finalize(ws)
    for ts in [x for x in list(cl_ticks) if x<maxt-7200]: del cl_ticks[ts]
for ws in sorted(list(bars)): finalize(ws)
import csv
with open(out,'w',newline='') as f:
    wtr=csv.DictWriter(f,fieldnames=['ws','win','z','tbo','tok','px','sz','sd'])
    wtr.writeheader()
    for r in rows: wtr.writerow(r)
print(f'{coin}: {len(rows)} pre-open prints -> {out}')
