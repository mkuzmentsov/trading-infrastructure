import pandas as pd, numpy as np
d=pd.read_parquet('full.parquet')
d['reb']=0.2*0.07*d.q*(1-d.q)
d['pnl']=d.f*((d.win-d.q)+d.reb)
f=d[d.f>0].copy()
QB=[0,0.15,0.30,0.45,0.60,0.75,0.90,0.96,0.999]
TB=[2,20,40,60,90,120,180,240,291]
f['qb']=pd.cut(f.q,QB); f['tb']=pd.cut(f.tl,TB,right=False)
def cell(g):
    per=g.groupby('ws',observed=True).agg(p=('pnl','sum'),s=('f','sum'))
    sh=per.s.sum(); ps=per.p.sum()/sh
    se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
    return pd.Series({'fills':len(g),'sh':int(sh),'c_sh':round(ps*100,3),
                      'se':round(se*100,3),'t':round(ps/se,2) if se>0 else np.nan,
                      'usd_d':round(per.p.sum()/6,1)})
print('=== net c/share, touch-joining two-sided maker, 50sh, LAT 0.2, queue-ahead modelled ===')
r=f.groupby(['tb','qb'],observed=True).apply(cell,include_groups=False)
print(r.reset_index().pivot(index='tb',columns='qb',values='c_sh').to_string())
print('\n--- t-stat ---')
print(r.reset_index().pivot(index='tb',columns='qb',values='t').to_string())
print('\n--- shares ---')
print(r.reset_index().pivot(index='tb',columns='qb',values='sh').to_string())
print('\n--- $/day (field-uncapped, our own 50sh clips) ---')
print(r.reset_index().pivot(index='tb',columns='qb',values='usd_d').to_string())
print('\n=== by tl only ==='); print(f.groupby('tb',observed=True).apply(cell,include_groups=False).to_string())
print('\n=== by q only ==='); print(f.groupby('qb',observed=True).apply(cell,include_groups=False).to_string())
