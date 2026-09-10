import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
f=pd.read_parquet('fills.parquet'); f['bar']=f.coin+'_'+f.ws.astype(str); f['loss']=(~f.right).astype(int)
CUT=pd.Timestamp('2026-09-07').date()
R={'V1 dB6<=-0.03':(f.dB6<=-0.03).fillna(False),
   'V3 rB6<=-0.30':(f.rB6<=-0.30).fillna(False),
   'V4 rB10<=-0.20':(f.rB10<=-0.20).fillna(False),
   'V5 ask<0.90 & dB6<=-0.03':((f.seen_ask<0.90)&(f.dB6<=-0.03).fillna(False)),
   'V6 ask<0.90':(f.seen_ask<0.90)}
print('=== BLOCK BOOTSTRAP over DAYS (10 days, 20k reps): $/day delta of the veto')
rng=np.random.default_rng(7); days=sorted(f.day.unique())
byday={d:f[f.day==d] for d in days}
for r,m in R.items():
    f['_m']=m
    per={d:(-byday[d].loc[m.loc[byday[d].index]].pnl.sum()) for d in days}
    arr=np.array([per[d] for d in days])
    reps=arr[rng.integers(0,10,size=(20000,10))].mean(axis=1)
    print(f'  {r:26s} mean={arr.mean():+7.2f}/day  95%CI [{np.percentile(reps,2.5):+7.2f},{np.percentile(reps,97.5):+7.2f}]  P(>0)={np.mean(reps>0):.3f}')
print('\n=== BLOCK BOOTSTRAP over days: LOSS-BAR reduction /day')
for r,m in R.items():
    per=[]
    for d in days:
        g=byday[d]; mm=m.loc[g.index]
        per.append(g[g.loss==1].bar.nunique()-g[~mm][lambda x:x.loss==1].bar.nunique())
    arr=np.array(per,float); reps=arr[rng.integers(0,10,size=(20000,10))].mean(axis=1)
    print(f'  {r:26s} mean={arr.mean():+5.2f} lossbars/day  95%CI [{np.percentile(reps,2.5):+.2f},{np.percentile(reps,97.5):+.2f}]  P(>0)={np.mean(reps>0):.3f}')

print('\n=== THIN-ESTIMATE test INSIDE the cheap band (is the §66 cell about est thinness?)')
c=f[f.seen_ask<0.90]
for lab,q in [('marg<=0.6',c.marg<=0.6),('marg<=0.5',c.marg<=0.5),('|est|<1bps',c.est_bps.abs()<1.0)]:
    a=c[q]; b=c[~q]
    print(f'  cheap band n={len(c)}  {lab}: flag n={len(a)} lossrate {a.loss.mean():.3f} pnl {a.pnl.sum():+.2f} | rest n={len(b)} lossrate {b.loss.mean():.3f} pnl {b.pnl.sum():+.2f}')
print('  cheap x drop6 x thin:')
print(c.groupby([(c.dB6<=-0.03).fillna(False),(c.marg<=0.6)]).agg(n=('loss','size'),loss=('loss','sum'),pnl=('pnl','sum')).round(2).to_string())

print('\n=== THE MISSING FLAGSHIP: sol 09-09 1524sh @0.0152')
x=f[(f.coin=='sol')&(f.day==pd.Timestamp('2026-09-09').date())]
print(x[['t','ws','tl','seen_ask','avg_px','filled','cost','est_bps','fb0','dB6','snapn','pnl']].to_string())
