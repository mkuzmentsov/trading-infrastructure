import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
f=pd.read_parquet('fills2.parquet'); CUT=pd.Timestamp('2026-09-07').date(); IS=f.day<=CUT
f['drop6']=(f.dB6<=-0.03).fillna(False)
print('=== S. COORDINATOR CHECK: the 0.55-0.80 band, on SEEN ask (gateable) vs FILL price (not gateable)')
for col,nm in [('seen_ask','SEEN ask (a live gate CAN key on this)'),('avg_px','FILL price (a gate CANNOT key on this)')]:
    f['bd']=pd.cut(f[col],[0,0.55,0.80,0.90,0.95,0.98,0.995,1.01])
    g=f.groupby('bd',observed=True).agg(n=('pnl','size'),loss=('loss','sum'),pnl=('pnl','sum'),
        d0909=('pnl',lambda s: s[f.loc[s.index,'day']==pd.Timestamp('2026-09-09').date()].sum()))
    g['roi%']=(g.pnl/f.groupby('bd',observed=True).cost.sum()*100)
    print(' --',nm); print(g.round(2).to_string())
print('\n=== S2. gate candidates on the SEEN ask alone ($/day = -blocked pnl)')
for lo,hi in [(0.55,0.80),(0.55,0.90),(0.55,0.85),(0.80,0.90)]:
    m=(f.seen_ask>=lo)&(f.seen_ask<hi)
    print(f'  block seen_ask in [{lo},{hi}): n={m.sum():3d} losses={f[m].loss.sum():2d} '
          f'$FULL{-f[m].pnl.sum()/10:+6.2f}/day  $OOS{-f[m&~IS].pnl.sum()/3:+6.2f}/day  $IS{-f[m&IS].pnl.sum()/7:+6.2f}/day')
print('\n=== T. HONEST IS-ONLY FIT: maximise IS loss-bars removed s.t. IS $ cost <= $5/day, then FREEZE')
rows=[]
for band in (0.80,0.85,0.90,0.95,0.98,1.01):
    for th in (-0.01,-0.03,-0.05,-0.10,-0.20,-0.30,None):
        m=(f.seen_ask<band)&(((f.dB6<=th).fillna(False))|f.nobid) if th is not None else (f.seen_ask<band)
        i=f[IS]; mi=m[IS]
        lb=i[i.loss==1].bar.nunique()-i[~mi][lambda x:x.loss==1].bar.nunique()
        c=-i[mi].pnl.sum()/7
        rows.append(dict(band=band,th=th,blk=int(mi.sum()),IS_lossbars_removed=lb,IS_dollar_day=round(c,2),ok=c>=-5.0))
R=pd.DataFrame(rows); R=R.sort_values(['ok','IS_lossbars_removed','IS_dollar_day'],ascending=[False,False,False])
print(R.head(12).to_string(index=False))
b=R.iloc[0]; band=b.band; th=b.th
m=(f.seen_ask<band)&(((f.dB6<=th).fillna(False))|f.nobid) if th is not None else (f.seen_ask<band)
o=f[~IS]; mo=m[~IS]
print(f'\n  >>> FROZEN by IS-only fit: seen_ask<{band} AND (dB6<={th} OR no bid)')
print(f'      OOS 09-08..10: blocked {int(mo.sum())} ({mo.sum()/3:.1f}/day of {len(o)/3:.0f} fills/day), '
      f'blocks {int(o[mo].loss.sum())} of {int(o.loss.sum())} losses')
print(f'      OOS loss bars/day {o[o.loss==1].bar.nunique()/3:.2f} -> {o[~mo][lambda x:x.loss==1].bar.nunique()/3:.2f}')
print(f'      OOS PnL ${o.pnl.sum():.2f} -> ${o[~mo].pnl.sum():.2f}  (+${-o[mo].pnl.sum()/3:.2f}/day)')
print(f'      FULL 10d PnL ${f.pnl.sum():.2f} -> ${f[~m].pnl.sum():.2f} (+${-f[m].pnl.sum()/10:.2f}/day); '
      f'loss bars/day {f[f.loss==1].bar.nunique()/10:.2f} -> {f[~m][lambda x:x.loss==1].bar.nunique()/10:.2f}')
f['FROZEN']=m
print('\n  LOO-day of the FROZEN rule:')
out={}
for g in sorted(f.day.unique()):
    s=f[f.day!=g]; nd=s.day.nunique()
    out[str(g)[5:]]=dict(dollar_day=round(-s[s.FROZEN].pnl.sum()/nd,2),
        lossbar_red=round((s[s.loss==1].bar.nunique()-s[~s.FROZEN][lambda x:x.loss==1].bar.nunique())/nd,2))
print(pd.DataFrame(out).T.to_string())
print('\n  LOO-coin of the FROZEN rule:')
out={}
for g in sorted(f.coin.unique()):
    s=f[f.coin!=g]; nd=s.day.nunique()
    out[g]=dict(dollar_day=round(-s[s.FROZEN].pnl.sum()/nd,2),
        lossbar_red=round((s[s.loss==1].bar.nunique()-s[~s.FROZEN][lambda x:x.loss==1].bar.nunique())/nd,2))
print(pd.DataFrame(out).T.to_string())
f.to_parquet('fills3.parquet',index=False)
