import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
f=pd.read_parquet('fills2.parquet')
CUT=pd.Timestamp('2026-09-07').date(); IS=f.day<=CUT
f['sweep']=(f.avg_px<=f.seen_ask*0.80)
f['drop6']=(f.dB6<=-0.03).fillna(False)
f['V5']=f.cheap&f.drop6
f['V5n']=f.cheap&(f.drop6|f.nobid)          # no-bid counts as a collapse
f['V6']=f.cheap
print('=== H. the SWEEP class (fill >=20% below the displayed ask) — the veto\'s real risk')
print(f.groupby(['cheap','drop6','sweep']).agg(n=('pnl','size'),loss=('loss','sum'),pnl=('pnl','sum')).round(2).to_string())
print('\n sweeps only:'); print(f[f.sweep].groupby(['cheap','drop6']).agg(n=('pnl','size'),loss=('loss','sum'),pnl=('pnl','sum'),avg=('pnl','mean')).round(2).to_string())
print('\n=== I. the >=0.90 band bid-drop class (what V1 would delete and V5 keeps)')
r=f[(~f.cheap)&f.drop6]
print(f'  n={len(r)} losses={r.loss.sum()} pnl=${r.pnl.sum():.2f}  sweeps={r.sweep.sum()} sweep$={r[r.sweep].pnl.sum():.2f}')
print('  by day:',{str(k)[5:]:round(v,2) for k,v in r.groupby('day').pnl.sum().items()})
print('\n=== J. FINAL RULE TABLE')
def ev(d,m,nd,lab):
    k=d[~m];v=d[m]
    return dict(rule=lab,n=len(d),blocked=len(v),blk_per_day=round(len(v)/nd,1),
      blk_loss=int(v.loss.sum()),blk_win=int((1-v.loss).sum()),
      lossbars_base=d[d.loss==1].bar.nunique(),lossbars_veto=k[k.loss==1].bar.nunique(),
      lb_day_base=round(d[d.loss==1].bar.nunique()/nd,2),lb_day_veto=round(k[k.loss==1].bar.nunique()/nd,2),
      pnl_base=round(d.pnl.sum(),2),pnl_veto=round(k.pnl.sum(),2),d_day=round(-v.pnl.sum()/nd,2))
rows=[]
for nm,d,nd in [('FULL(10d)',f,10),('IS(7d)',f[IS],7),('OOS(3d)',f[~IS],3)]:
    for lab in ['V5','V5n','V6']:
        r=ev(d,d[lab],nd,f'{nm} {lab}'); rows.append(r)
print(pd.DataFrame(rows).to_string(index=False))
print('\n=== K. LOO for V5n')
for by in ['day','coin']:
    out={}
    for g in sorted(f[by].unique()):
        s=f[f[by]!=g]; nd=s.day.nunique()
        out[str(g)[5:] if by=='day' else g]=dict(
            d_day=round(-s[s.V5n].pnl.sum()/nd,2),
            lb_red=round((s[s.loss==1].bar.nunique()-s[~s.V5n][lambda x:x.loss==1].bar.nunique())/nd,2))
    print(' LOO-'+by); print(pd.DataFrame(out).T.to_string())
print('\n=== L. per coin, V5n, full sample')
print(f.groupby('coin').apply(lambda d: pd.Series(dict(n=len(d),blocked=d.V5n.sum(),blk_loss=d[d.V5n].loss.sum(),
    blk_pnl=round(d[d.V5n].pnl.sum(),2),lossbars=d[d.loss==1].bar.nunique(),
    lossbars_v=d[~d.V5n][lambda x:x.loss==1].bar.nunique())),include_groups=False).to_string())
print('\n=== M. threshold sensitivity of V5n (ask floor x drop threshold), full sample / OOS')
for band in (0.85,0.90,0.95,0.98):
    line=[]
    for th in (-0.01,-0.03,-0.05,-0.10,-0.20):
        m=(f.seen_ask<band)&((f.dB6<=th).fillna(False)|f.nobid)
        o=(~IS)&m
        line.append(f'{th}: blk{m.sum():3d} loss{f[m].loss.sum():2d} $ALL{-f[m].pnl.sum():+7.1f} $OOS{-f[o].pnl.sum():+7.1f}')
    print(f' ask<{band}: '+' | '.join(line))
