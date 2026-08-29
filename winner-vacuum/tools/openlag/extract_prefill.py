#!/usr/bin/env python3
"""Pre-open fill physics: from next1 rows, per bar collect
(a) BUY prints in the pre-open window bucketed by seconds-before-open
    (0-1,1-3,3-10,10-60,60+) with px stats,
(b) the displayed ask on each side at ws-3 and ws-1, and whether prints
    at-or-below that ask occurred in [ws-3, ws).
Usage: extract_prefill.py <coin> <mrec_dir> <out_csv>
"""
import sys, os, re, gzip, glob, json

coin, mdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
r_ws  = re.compile(r'"ws":([0-9]+)')
r_tl  = re.compile(r'"tl":(-?[0-9.]+)')
r_ua  = re.compile(r'"ua":([0-9.]+|null)')
r_da  = re.compile(r'"da":([0-9.]+|null)')
r_win = re.compile(r'"win":"(UP|DOWN)"')
r_trd = re.compile(r'"trd":(\[\[.*\]\])')

def fnum(rx, line):
    m = rx.search(line)
    if not m: return None
    v = m.group(1)
    return None if v=='null' else float(v)

bars={}
def bar(ws):
    b=bars.get(ws)
    if b is None:
        b=bars[ws]={'win':None,'q3':{},'q1':{},'pr':{}, 'seen':set(), 'hit3':{}}
    return b

BK=[(0,1),(1,3),(3,10),(10,60),(60,900)]
FIELDS=['ws','win','ua3','da3','ua1','da1']
for s in ('U','D'):
    for i,_ in enumerate(BK): FIELDS+=[f'pb_{s}_{i}_sh',f'pb_{s}_{i}_usd']
FIELDS+=['hit3_U','hit3_D']  # shares printed at<=ask3 on that side within [ws-3,ws)

rows_out=[]
def finalize(ws):
    b=bars.pop(ws,None)
    if b is None or b['win'] is None: return
    row={'ws':ws,'win':b['win'],
         'ua3':b['q3'].get('ua'),'da3':b['q3'].get('da'),
         'ua1':b['q1'].get('ua'),'da1':b['q1'].get('da')}
    for s in ('U','D'):
        for i,_ in enumerate(BK):
            v=b['pr'].get((s,i),(0.0,0.0))
            row[f'pb_{s}_{i}_sh']=round(v[0],1); row[f'pb_{s}_{i}_usd']=round(v[1],2)
        row[f'hit3_{s}']=round(b['hit3'].get(s,0.0),1)
    rows_out.append(row)

files=sorted(glob.glob(os.path.join(mdir,coin,f'{coin}-mrec-*.jsonl.gz')))
maxws=0
for fp in files:
    try:
        with gzip.open(fp,'rt') as f:
            for line in f:
                if '"ev":"RES"' in line:
                    m=r_win.search(line); w=r_ws.search(line)
                    if m and w: bar(int(w.group(1)))['win']=m.group(1)
                    continue
                if '"role":"next1"' not in line: continue
                w=r_ws.search(line)
                tl=fnum(r_tl,line)
                if not w or tl is None or tl<=300: continue
                ws=int(w.group(1))
                if ws>maxws: maxws=ws
                b=bar(ws)
                tb=tl-300.0  # seconds before open
                if tb<=3.2 and 'ua' not in b['q3']:
                    b['q3']={'ua':fnum(r_ua,line),'da':fnum(r_da,line)}
                if tb<=1.2 and 'ua' not in b['q1']:
                    b['q1']={'ua':fnum(r_ua,line),'da':fnum(r_da,line)}
                mtr=r_trd.search(line)
                if not mtr: continue
                try: trs=json.loads(mtr.group(1))
                except Exception: continue
                for tr in trs:
                    ts_,tok,px,sz,sd=tr[0],tr[1],float(tr[2]),float(tr[3]),tr[4]
                    if sd!='BUY': continue
                    tbo=ws-ts_  # seconds before open
                    if tbo<0 or tbo>900: continue
                    dk=(ts_,tok,px,sz)
                    if dk in b['seen']: continue
                    b['seen'].add(dk)
                    for i,(lo,hi) in enumerate(BK):
                        if lo<=tbo<hi:
                            s=b['pr'].get((tok,i),(0.0,0.0))
                            b['pr'][(tok,i)]=(s[0]+sz,s[1]+sz*px)
                            break
                    if tbo<3.0:
                        a3=b['q3'].get('ua' if tok=='U' else 'da')
                        if a3 and px<=a3+1e-9:
                            b['hit3'][tok]=b['hit3'].get(tok,0.0)+sz
    except (EOFError,OSError) as e:
        print(f'WARN {fp}: {e}',file=sys.stderr)
    for ws in [x for x in list(bars) if x<maxws-900]: finalize(ws)
for ws in sorted(list(bars)): finalize(ws)
import csv
with open(out,'w',newline='') as f:
    wtr=csv.DictWriter(f,fieldnames=FIELDS); wtr.writeheader()
    for r in sorted(rows_out,key=lambda x:x['ws']): wtr.writerow(r)
print(f'{coin}: {len(rows_out)} bars -> {out}')
