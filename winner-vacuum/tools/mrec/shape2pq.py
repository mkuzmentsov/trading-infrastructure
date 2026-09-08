"""Build a BOOK-SHAPE panel: full top-3 ladders BOTH sides BOTH tokens, aligned to the
panelflow3 (coin,ws,tlk) grid, plus 5/10/20s lags.  Cheap: reads snapcur columns only."""
import pandas as pd, numpy as np
COLS=['coin','ws','tl',
      'uad0p','uad0s','uad1p','uad1s','uad2p','uad2s',
      'ubd0p','ubd0s','ubd1p','ubd1s','ubd2p','ubd2s',
      'dad0p','dad0s','dad1p','dad1s','dad2p','dad2s',
      'dbd0p','dbd0s','dbd1p','dbd1s','dbd2p','dbd2s']
s=pd.read_parquet('pq/snapcur.parquet',columns=COLS)
print('read',s.shape,flush=True)
s=s[(s.tl>=0)&(s.tl<=50)].copy()
s['tlk']=np.ceil(s.tl).astype(int)
s=s.sort_values(['coin','ws','tl'])
s=s.groupby(['coin','ws','tlk'],observed=True).first().reset_index()
print('grid',s.shape,flush=True)
p=pd.read_parquet('pq/panelflow3.parquet')
m=p.merge(s.drop(columns=['tl']),on=['coin','ws','tlk'],how='left',suffixes=('','_x'))
print('merged',m.shape,flush=True)
up=(m.side=='UP').values
def pick(u,d):
    return np.where(up,m[u].values,m[d].values)
# favourite side ladders
for i in range(3):
    m[f'fa{i}p']=pick(f'uad{i}p',f'dad{i}p'); m[f'fa{i}s']=pick(f'uad{i}s',f'dad{i}s')
    m[f'fb{i}p']=pick(f'ubd{i}p',f'dbd{i}p'); m[f'fb{i}s']=pick(f'ubd{i}s',f'dbd{i}s')
    # dog side (the other token)
    m[f'ga{i}p']=pick(f'dad{i}p',f'uad{i}p'); m[f'ga{i}s']=pick(f'dad{i}s',f'uad{i}s')
    m[f'gb{i}p']=pick(f'dbd{i}p',f'ubd{i}p'); m[f'gb{i}s']=pick(f'dbd{i}s',f'ubd{i}s')
nz=lambda x: np.nan_to_num(m[x].values)
# $ depth top-3 each side of the favourite
m['adep']=sum(nz(f'fa{i}p')*nz(f'fa{i}s') for i in range(3))
m['bdep']=sum(nz(f'fb{i}p')*nz(f'fb{i}s') for i in range(3))
m['ashr']=sum(nz(f'fa{i}s') for i in range(3)); m['bshr']=sum(nz(f'fb{i}s') for i in range(3))
m['imb']=(m.bdep-m.adep)/np.maximum(m.bdep+m.adep,1e-9)          # >0 = bid-heavy
m['imbs']=(m.bshr-m.ashr)/np.maximum(m.bshr+m.ashr,1e-9)         # share-weighted
m['spread']=m.fa0p-m.fb0p
m['agap']=m.fa1p-m.fa0p                                          # ask ladder gap
m['bgap']=m.fb0p-m.fb1p
# dog-side depth (mirror book): dog bid $ = people willing to buy the LOSER
m['gadep']=sum(nz(f'ga{i}p')*nz(f'ga{i}s') for i in range(3))
m['gbdep']=sum(nz(f'gb{i}p')*nz(f'gb{i}s') for i in range(3))
# lags
base=m[['coin','ws','tlk','adep','bdep','imb','imbs','spread','ashr','bshr']].copy()
for L in (5,10,20):
    b=base.copy(); b['tlk']=b.tlk-L
    b=b.rename(columns={c:f'{c}_{L}' for c in ('adep','bdep','imb','imbs','spread','ashr','bshr')})
    m=m.merge(b,on=['coin','ws','tlk'],how='left')
    m[f'dimb{L}']=m.imb-m[f'imb_{L}']
    m[f'dbdep{L}']=np.log1p(m.bdep)-np.log1p(m[f'bdep_{L}'])
    m[f'dadep{L}']=np.log1p(m.adep)-np.log1p(m[f'adep_{L}'])
m.to_parquet('shape.parquet',index=False)
print('done',m.shape)
print(m[['adep','bdep','imb','spread','agap','gbdep']].describe().round(3))
