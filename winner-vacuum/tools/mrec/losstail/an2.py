import numpy as np,pandas as pd
pd.set_option('display.width',260); pd.set_option('display.max_columns',60)
f=pd.read_parquet('fills.parquet')
f['bar']=f.coin+'_'+f.ws.astype(str); f['loss']=(~f.right).astype(int)
NDAY_IS=f[f.day<=pd.Timestamp('2026-09-07').date()].day.nunique()
NDAY_OOS=f[f.day>pd.Timestamp('2026-09-07').date()].day.nunique()
print('IS days',NDAY_IS,'OOS days',NDAY_OOS)

def clust_se(x,g):
    """cluster-robust SE of the mean of x, clustering on g"""
    x=np.asarray(x,float); n=len(x); m=x.mean()
    d=pd.Series(x-m).groupby(np.asarray(g)).sum().values
    return float(np.sqrt((d**2).sum())/n)

def score(df,mask,label,nd):
    """mask=True means VETOED (blocked)."""
    b=df[~mask]; v=df[mask]
    r=dict(rule=label, n=len(df), blocked=len(v), blk_loss=int(v.loss.sum()), blk_win=int((1-v.loss).sum()),
           blk_pnl=round(v.pnl.sum(),2),
           loss_kept=int(b.loss.sum()), lossper_day=round(b.loss.sum()/nd,2),
           base_lossper_day=round(df.loss.sum()/nd,2),
           pnl_day=round(b.pnl.sum()/nd,2), base_pnl_day=round(df.pnl.sum()/nd,2),
           delta_day=round(-v.pnl.sum()/nd,2))
    lr_v=v.loss.mean() if len(v) else np.nan; lr_k=b.loss.mean() if len(b) else np.nan
    r['lossrate_blk']=round(lr_v,4); r['lossrate_kept']=round(lr_k,4)
    r['lift']=round(lr_v/lr_k,2) if lr_k>0 else np.nan
    return r

f['drop6']=(f.dB6<=-0.03); f['drop10']=(f.dB10<=-0.03); f['drop20']=(f.dB20<=-0.03)
f['rdrop6']=(f.rB6<=-0.20); f['rdrop10']=(f.rB10<=-0.20); f['rdrop30_6']=(f.rB6<=-0.30)
f['thin']=(f.marg<=0.6)
IS=f.day<=pd.Timestamp('2026-09-07').date()

print('\n=== A. FULL SAMPLE: single-variable splits (all fills, n=%d)'%len(f))
rows=[]
for lab,m in [('dB6<=-0.03',f.drop6),('dB10<=-0.03',f.drop10),('dB20<=-0.03',f.drop20),
              ('rB6<=-0.20',f.rdrop6),('rB6<=-0.30',f.rdrop30_6),('rB10<=-0.20',f.rdrop10),
              ('marg<=0.6 (thin est)',f.thin),
              ('dA6<=-0.03 (ASK placebo)',f.dA6<=-0.03),
              ('seen_ask<0.90',f.seen_ask<0.90)]:
    rows.append(score(f,m.fillna(False),lab,10))
print(pd.DataFrame(rows).to_string(index=False))

print('\n=== B. bar-clustered t on the loss indicator: loss ~ flag')
for lab,col in [('dB6<=-0.03','drop6'),('dB10<=-0.03','drop10'),('dB20<=-0.03','drop20'),
                ('rB6<=-0.30','rdrop30_6'),('rB10<=-0.20','rdrop10'),('thin marg<=0.6','thin')]:
    for nm,d in [('ALL',f),('IS<=09-07',f[IS]),('OOS 09-08..10',f[~IS])]:
        d=d[d[col].notna()]
        a=d[d[col]==True]; b=d[d[col]==False]
        if len(a)<3 or len(b)<3: continue
        diff=a.loss.mean()-b.loss.mean()
        se=np.sqrt(clust_se(a.loss,a.bar)**2+clust_se(b.loss,b.bar)**2)
        print(f'  {lab:18s} {nm:14s} n={len(d):4d} flag={len(a):4d} lossrate {a.loss.mean():.4f} vs {b.loss.mean():.4f} '
              f'diff={diff:+.4f} clSE={se:.4f} t={diff/se if se>0 else np.nan:+.2f}')
