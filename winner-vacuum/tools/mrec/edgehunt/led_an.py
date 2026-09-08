"""Lead 3: live ledger, 7 coins, current era (>=08-22)."""
import pandas as pd,numpy as np
O=pd.read_parquet('orders.parquet'); S=pd.read_parquet('settles.parquet')
O['day']=pd.to_datetime(O.t,unit='s',utc=True).dt.date; S['day']=pd.to_datetime(S.t,unit='s',utc=True).dt.date
print('orders',len(O),O.day.min(),'->',O.day.max(),' settles',len(S))
W=S.groupby(['coin','bar']).agg(won=('won','first'),sside=('side','first'),spnl=('pnl','sum'),scost=('cost','sum'),sfilled=('filled','sum')).reset_index()
m=O[O.matched==True].merge(W,on=['coin','bar'],how='inner')
m=m[m.day>=pd.Timestamp('2026-08-22').date()]
m['win']=(m.side==m.won); m['pnl']=np.where(m.win,m.filled-m.cost,-m.cost)
m['impr']=(m.seen_ask-m.avg_px)/m.seen_ask
m['cls']=np.where(m.impr>=0.05,'SWEEP',np.where(m.avg_px>m.seen_ask+1e-9,'ABOVE','AT'))
def tab(g):
    c=g.cost.sum(); return pd.Series({'fills':len(g),'loss':int((~g.win).sum()),'cost':round(c,0),'pnl':round(g.pnl.sum(),2),'roi%':round(g.pnl.sum()/c*100,2) if c else np.nan})
print('\n=== current era fills by class ==='); print(m.groupby('cls').apply(tab,include_groups=False).to_string())
print('fleet total pnl',round(m.pnl.sum(),2),'days',m.day.nunique(),'per day',round(m.pnl.sum()/m.day.nunique(),2))
print('\n=== by displayed ask (seen_ask) band ===')
m['sb']=pd.cut(m.seen_ask,[0,0.75,0.9,0.95,0.98,0.985,0.995,1.0],right=False)
print(m.groupby('sb',observed=True).apply(tab,include_groups=False).to_string())
print('\n=== seen_ask EXACTLY 0.99 vs 0.98 vs 0.985 etc ===')
m['sa']=m.seen_ask.round(3)
print(m[m.seen_ask>=0.97].groupby('sa').apply(tab,include_groups=False).to_string())
print('\n=== SWEEP by seen_ask exact ===')
print(m[m.cls=='SWEEP'].groupby('sa').apply(tab,include_groups=False).to_string())
print('\n=== restriction: fire ONLY at seen_ask==0.99 (vs all >=0.98) ===')
for lab,q in [('all >=0.98',m.seen_ask>=0.98-1e-9),('==0.99',(m.sa==0.99)),('==0.98',(m.sa==0.98)),('>=0.985',m.seen_ask>=0.985-1e-9),('<0.98',m.seen_ask<0.98-1e-9)]:
    g=m[q]; print(f'{lab:12s}',tab(g).to_dict(), ' days+',int((g.groupby("day").pnl.sum()>0).sum()),'/',g.day.nunique())
print('\n=== per coin, seen==0.99 ==='); print(m[m.sa==0.99].groupby('coin').apply(tab,include_groups=False).to_string())
print('\n=== per coin, seen==0.98 ==='); print(m[m.sa==0.98].groupby('coin').apply(tab,include_groups=False).to_string())
print('\n=== tl gradient, >=0.98 band, by coin ===')
m['tb']=pd.cut(m.tl,[0,12,16,20,31])
print(m[m.seen_ask>=0.98-1e-9].groupby(['tb'],observed=True).apply(tab,include_groups=False).to_string())
print(m[m.seen_ask>=0.98-1e-9].groupby(['coin','tb'],observed=True).apply(tab,include_groups=False).to_string())
print('\n=== clip index (1st vs ladder) & ms latency ===')
print(m.groupby('clip').apply(tab,include_groups=False).to_string())
print(m.ms.describe().round(0).to_string())
print('\n=== est_bps band x seen band ===')
m['eb']=pd.cut(m.est_bps.abs(),[0,0.5,1,2,4,8,1000])
print(m.groupby(['eb','sb'],observed=True).apply(tab,include_groups=False).unstack('sb')['roi%'].to_string())
print(m.groupby(['eb'],observed=True).apply(tab,include_groups=False).to_string())

