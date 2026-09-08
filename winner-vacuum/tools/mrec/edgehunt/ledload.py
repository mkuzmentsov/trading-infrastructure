import json,glob,gzip,collections,pandas as pd,numpy as np
def load(D='led'):
    O=[];S=[];R=[]
    for f in sorted(glob.glob(f'{D}/*')):
        op=gzip.open if f.endswith('.gz') else open
        coin=f.split('/')[-1].split('.')[0]
        for l in op(f,'rt'):
            try: d=json.loads(l)
            except: continue
            e=d.get('ev')
            if e=='PF_TE_WHALE_ORDER': d['coin']=coin; O.append(d)
            elif e=='PF_TE_LIVE_SETTLE': d['coin']=coin; S.append(d)
            elif e in ('PF_TE_SNIPE_ORDER','PF_TE_SNIPE_REST','PF_TE_DISLOC_ORDER'): d['coin']=coin; R.append(d)
    return pd.DataFrame(O),pd.DataFrame(S),pd.DataFrame(R)
if __name__=='__main__':
    O,S,R=load()
    print('orders',len(O),'settles',len(S),'other',len(R))
    print('order cols',list(O.columns)); print(O.head(2).T.to_string()[:2500])
    print('settle cols',list(S.columns)); print(S.head(2).T.to_string()[:1500])
    O.to_parquet('orders.parquet',index=False); S.to_parquet('settles.parquet',index=False)
    print(O.groupby('coin').size()); print('ts range',pd.to_datetime(O.ts.min(),unit='s') if 'ts' in O else O.iloc[0])
