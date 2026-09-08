"""Extract SNAP rows with role in (post, next1) from raw mrec files -> rolepq/<coin>.parquet"""
import gzip, json, os, sys, glob, pandas as pd
RAW='/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec'
coin=sys.argv[1]; rows=[]
for f in sorted(glob.glob(f'{RAW}/{coin}/{coin}-mrec-*.jsonl.gz')):
    with gzip.open(f,'rt') as fh:
        for l in fh:
            if '"ev":"SNAP"' not in l or ('"role":"post"' not in l and '"role":"next1"' not in l): continue
            try: d=json.loads(l)
            except Exception: continue
            r=dict(t=d['t'],ws=d['ws'],role=d['role'],tl=d['tl'],ub=d.get('ub'),ubs=d.get('ubs'),ua=d.get('ua'),uas=d.get('uas'),
                   db=d.get('db'),dbs=d.get('dbs'),da=d.get('da'),das=d.get('das'),evage=d.get('evage'),vol=d.get('vol'),volsh=d.get('volsh'))
            for side in ('ubd','uad','dbd','dad'):
                L=d.get(side) or []
                for i in range(3):
                    r[f'{side}{i}p']=L[i][0] if i<len(L) else None; r[f'{side}{i}s']=L[i][1] if i<len(L) else None
            rows.append(r)
pd.DataFrame(rows).to_parquet(f'rolepq/{coin}.parquet',index=False); print(coin,len(rows))
