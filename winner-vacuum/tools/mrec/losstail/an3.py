import numpy as np,pandas as pd
pd.set_option('display.width',260); pd.set_option('display.max_columns',60)
f=pd.read_parquet('fills.parquet'); f['bar']=f.coin+'_'+f.ws.astype(str); f['loss']=(~f.right).astype(int)
f['drop6']=(f.dB6<=-0.03).fillna(False); f['cheap']=(f.seen_ask<0.90); f['thin']=(f.marg<=0.6)
IS=f.day<=pd.Timestamp('2026-09-07').date()
def cse(x,g):
    x=np.asarray(x,float);n=len(x);m=x.mean()
    d=pd.Series(x-m).groupby(np.asarray(g)).sum().values
    return float(np.sqrt((d**2).sum())/n)
print('=== C. 2x2  bid-drop x cheap-ask  (is dB just a proxy for a cheap displayed ask?)')
for nm,d in [('ALL',f),('OOS 09-08..10',f[~IS])]:
    print(' --',nm)
    g=d.groupby(['cheap','drop6']).agg(n=('loss','size'),loss=('loss','sum'),lr=('loss','mean'),pnl=('pnl','sum'),
                                       avgwin=('pnl',lambda s:s[s>0].mean()))
    print(g.round(3).to_string())
print('\n=== D. marginal tests (does each variable add inside the other\'s kept set?)')
for nm,d in [('ALL',f),('IS',f[IS]),('OOS',f[~IS])]:
    for lab,sub,col in [('dB6 inside ask>=0.90', d[~d.cheap], 'drop6'),
                        ('dB6 inside ask<0.90',  d[d.cheap],  'drop6'),
                        ('cheap inside dB6-kept',d[~d.drop6], 'cheap'),
                        ('cheap inside dB6-flag',d[d.drop6],  'cheap'),
                        ('thin inside dB6-kept', d[~d.drop6], 'thin'),
                        ('thin inside dB6-flag', d[d.drop6],  'thin')]:
        a=sub[sub[col]]; b=sub[~sub[col]]
        if len(a)<3 or len(b)<3: print(f'  {nm:4s} {lab:24s} n/a'); continue
        diff=a.loss.mean()-b.loss.mean(); se=np.sqrt(cse(a.loss,a.bar)**2+cse(b.loss,b.bar)**2)
        print(f'  {nm:4s} {lab:24s} flag={len(a):4d}/{len(sub):4d} lr {a.loss.mean():.4f} vs {b.loss.mean():.4f} t={diff/se if se>0 else np.nan:+.2f}  blk$={a.pnl.sum():+8.2f}')
print('\n=== E. joint logit (bar-clustered), loss ~ drop6 + cheap + thin (+interaction)')
import statsmodels.api as sm
for nm,d in [('ALL',f),('IS',f[IS]),('OOS',f[~IS])]:
    X=pd.DataFrame({'drop6':d.drop6.astype(float),'cheap':d.cheap.astype(float),'thin':d.thin.astype(float)})
    X['drop6_x_thin']=X.drop6*X.thin; X=sm.add_constant(X)
    try:
        m=sm.Logit(d.loss.values,X).fit(disp=0,method='bfgs')
        r=m.get_robustcov_results(cov_type='cluster',groups=pd.factorize(d.bar)[0])
        print(f' -- {nm}: n={len(d)}')
        print(pd.DataFrame({'coef':r.params,'z':r.tvalues,'p':r.pvalues},index=X.columns).round(3).to_string())
    except Exception as e: print(nm,'logit failed',e)
