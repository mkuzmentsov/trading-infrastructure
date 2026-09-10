import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
f=pd.read_parquet('fills2.parquet')
CUT=pd.Timestamp('2026-09-07').date(); IS=f.day<=CUT
f['drop6']=(f.dB6<=-0.03).fillna(False)
f['V5n']=f.cheap&(f.drop6|f.nobid); f['V6']=f.cheap
f['V1']=f.drop6|f.nobid
print('=== N. COST DECOMPOSITION ($/day), full 10d and OOS 3d')
for lab in ['V1','V5n','V6']:
    for nm,d,nd in [('FULL',f,10),('OOS',f[~IS],3)]:
        v=d[d[lab]]
        w=v[v.loss==0].pnl.sum(); l=v[v.loss==1].pnl.sum()
        print(f'  {lab:4s} {nm:4s}: forfeits {(v.loss==0).sum():3d} wins = ${w/nd:6.2f}/day | avoids {(v.loss==1).sum():3d} losses = ${-l/nd:6.2f}/day | NET {-(w+l)/nd:+6.2f}/day')
print('\n=== O. IS-ONLY parameter choice (fit on <=09-07), then frozen on OOS')
best=None
for band in (0.80,0.85,0.90,0.95,0.98,1.01):
    for th in (-0.01,-0.03,-0.05,-0.10,-0.20,-0.30,-9):
        m=(f.seen_ask<band)&(((f.dB6<=th).fillna(False))|f.nobid) if th>-9 else (f.seen_ask<band)
        i=f[IS]; mi=m[IS]
        lb=i[i.loss==1].bar.nunique()-i[~mi][lambda x:x.loss==1].bar.nunique()
        dd=-i[mi].pnl.sum()
        rec=(lb, dd, band, th, int(mi.sum()))
        if best is None or (rec[0],rec[1])>(best[0],best[1]): best=rec
        if band in (0.90,) or th==-9:
            print(f'   IS band<{band} th{th}: blocked{int(mi.sum()):3d} lossbars_removed {lb} IS$ {dd:+7.2f}')
print('  IS argmax (lossbars removed, tie-break $):',best)
b=best[2]; t=best[3]
m=(f.seen_ask<b)&(((f.dB6<=t).fillna(False))|f.nobid) if t>-9 else (f.seen_ask<b)
o=f[~IS]; mo=m[~IS]
print(f'  FROZEN rule ask<{b} & dB6<={t}  -> OOS: blocked {int(mo.sum())} ({mo.sum()/3:.1f}/day), '
      f'lossbars {o[o.loss==1].bar.nunique()}->{o[~mo][lambda x:x.loss==1].bar.nunique()}, '
      f'PnL {o.pnl.sum():.2f} -> {o[~mo].pnl.sum():.2f} (+${-o[mo].pnl.sum()/3:.2f}/day)')
print('\n=== P. per-coin V6 (MIN_ASK 0.90) — does btc still lose, as the live ledger said?')
print(f.groupby('coin').apply(lambda d: pd.Series(dict(n=len(d),blk=d.V6.sum(),blk_loss=d[d.V6].loss.sum(),
    blk_pnl=round(d[d.V6].pnl.sum(),2))),include_groups=False).to_string())
print('\n=== Q. blocked-win detail for V5n (what we give up)')
v=f[f.V5n&(f.loss==0)]
print(v[['coin','day','tl','seen_ask','avg_px','filled','pnl','dB6','fb0']].sort_values('pnl',ascending=False).head(12).to_string())
print(' blocked wins pnl total',round(v.pnl.sum(),2),' of which top-3:',round(v.pnl.nlargest(3).sum(),2))
print('\n=== R. permutation: shuffle the drop flag within (coin,day), 5000 reps, OOS loss-rate diff')
rng=np.random.default_rng(3); o=f[~IS].copy()
obs=o[o.V5n].loss.mean()-o[~o.V5n].loss.mean(); cnt=0
for _ in range(5000):
    s=o.groupby(['coin','day'],observed=True).V5n.transform(lambda x: rng.permutation(x.values))
    d=o[s].loss.mean()-o[~s].loss.mean()
    if d>=obs: cnt+=1
print(f'  observed OOS loss-rate diff {obs:.4f}; permutation p={cnt/5000:.4f}')
