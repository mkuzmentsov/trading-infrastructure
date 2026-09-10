import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
PQ='/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/pq'
f=pd.read_parquet('fills.parquet'); f['bar']=f.coin+'_'+f.ws.astype(str); f['loss']=(~f.right).astype(int)
f['tlk']=np.ceil(f.tl).astype(int)
pf=pd.read_parquet(PQ+'/panelflow2.parquet',columns=['coin','ws','tlk','mf10','mf30','dp10','dp30','vol','cov','fav_bid','fav_ask'])
f=f.merge(pf,on=['coin','ws','tlk'],how='left',suffixes=('','_pan'))
f['nobid']=f.fb0.isna()|(f.fb0<=0.02)
f['spr']=f.seen_ask-f.fb0
f['bidfrac']=f.fb0/f.seen_ask
f['cheap']=f.seen_ask<0.90
CUT=pd.Timestamp('2026-09-07').date(); IS=f.day<=CUT
def cse(x,g):
    x=np.asarray(x,float);n=len(x);m=x.mean()
    return float(np.sqrt((pd.Series(x-m).groupby(np.asarray(g)).sum().values**2).sum())/n)
def T(d,q,lab):
    q=q.fillna(False) if hasattr(q,'fillna') else q
    a=d[q];b=d[~q]
    if len(a)<3 or len(b)<3: return None
    diff=a.loss.mean()-b.loss.mean(); se=np.sqrt(cse(a.loss,a.bar)**2+cse(b.loss,b.bar)**2)
    return dict(rule=lab,nflag=len(a),lr_flag=round(a.loss.mean(),3),lr_kept=round(b.loss.mean(),4),
                t=round(diff/se,2) if se>0 else np.nan, blk_loss=int(a.loss.sum()), blk_pnl=round(a.pnl.sum(),2))
print('=== F. CANDIDATE DISCRIMINATORS (no history needed vs history)  — ALL / OOS')
cands=[('no bid or bid<=0.02', lambda d: d.nobid),
       ('bid<=0.05', lambda d: d.fb0<=0.05),
       ('spread ask-bid >=0.10', lambda d: d.spr>=0.10),
       ('spread ask-bid >=0.20', lambda d: d.spr>=0.20),
       ('bid/ask <= 0.80', lambda d: d.bidfrac<=0.80),
       ('bid/ask <= 0.60', lambda d: d.bidfrac<=0.60),
       ('dB6<=-0.03', lambda d:(d.dB6<=-0.03)),
       ('cheap & dB6<=-0.03', lambda d:(d.cheap&(d.dB6<=-0.03).fillna(False))),
       ('cheap & spr>=0.10', lambda d:(d.cheap&(d.spr>=0.10))),
       ('cheap', lambda d: d.cheap),
       ('mf30 adverse (<0)', lambda d: d.mf30<0),
       ('dp30 adverse (<0)', lambda d: d.dp30<0),
       ('vol>=10', lambda d: d.vol>=10),
       ('cov<0.7', lambda d: d['cov']<0.7),
       ('tl>=18', lambda d: d.tl>=18),
       ]
for nm,d in [('ALL',f),('OOS',f[~IS])]:
    print(' --',nm)
    print(pd.DataFrame([r for r in (T(d,fn(d),lab) for lab,fn in cands) if r]).to_string(index=False))
print('\n=== G. spread vs bid-drop: which survives jointly? (LPM, bar-clustered)')
import statsmodels.api as sm
for nm,d in [('ALL',f),('IS',f[IS]),('OOS',f[~IS])]:
    X=pd.DataFrame({'cheap':d.cheap.astype(float),'drop6':(d.dB6<=-0.03).fillna(False).astype(float),
                    'wide_spr':(d.spr>=0.10).fillna(True).astype(float)})
    X=sm.add_constant(X)
    m=sm.OLS(d.loss.values,X.values).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(d.bar)[0]})
    print(' --',nm,'n=',len(d)); print(pd.DataFrame({'coef':m.params,'t':m.tvalues,'p':m.pvalues},index=X.columns).round(4).to_string())
f.to_parquet('fills2.parquet',index=False)
