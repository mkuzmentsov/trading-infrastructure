import numpy as np,pandas as pd
pd.set_option('display.width',300); pd.set_option('display.max_columns',80)
f=pd.read_parquet('fills2.parquet'); CUT=pd.Timestamp('2026-09-07').date(); IS=f.day<=CUT
def rule(d,band,th): return (d.seen_ask<band)&(((d.dB6<=th).fillna(False))|d.nobid)
f['F']=rule(f,0.98,-0.01)
def cse(x,g):
    x=np.asarray(x,float);n=len(x);m=x.mean()
    return float(np.sqrt((pd.Series(x-m).groupby(np.asarray(g)).sum().values**2).sum())/n)
print('=== U. FROZEN RULE  seen_ask<0.98 AND (dB6<=-0.01 OR no bid)   [chosen on IS only]')
for nm,d,nd in [('FULL 10d',f,10),('IS 7d',f[IS],7),('OOS 3d',f[~IS],3)]:
    v=d[d.F]; k=d[~d.F]
    a=v.loss.mean(); b=k.loss.mean(); se=np.sqrt(cse(v.loss,v.bar)**2+cse(k.loss,k.bar)**2)
    print(f' {nm}: fills/day {len(d)/nd:5.1f}  blocked/day {len(v)/nd:4.1f} ({len(v)/len(d)*100:.1f}%)  '
          f'blocked lossrate {a:.3f} vs kept {b:.4f} (t={(a-b)/se:+.2f})')
    print(f'      losses {int(d.loss.sum())} -> {int(k.loss.sum())} | loss BARS/day {d[d.loss==1].bar.nunique()/nd:.2f} -> {k[k.loss==1].bar.nunique()/nd:.2f}')
    print(f'      forfeits {int((v.loss==0).sum())} wins = ${v[v.loss==0].pnl.sum()/nd:.2f}/day | avoids {int(v.loss.sum())} losses = ${-v[v.loss==1].pnl.sum()/nd:.2f}/day | NET ${-v.pnl.sum()/nd:+.2f}/day')
    print(f'      PnL ${d.pnl.sum():.2f} -> ${k.pnl.sum():.2f}')
print('\n=== V. contribution of the "no bid" clause alone')
print('  fills with no/zero bid:',int(f.nobid.sum()),' losses:',int(f[f.nobid].loss.sum()),' pnl:',round(f[f.nobid].pnl.sum(),2))
print('  rule WITHOUT the nobid clause, OOS $:',round(-f[(~IS)&rule(f,0.98,-0.01)&~f.nobid].pnl.sum()/3,2))
print('\n=== W. threshold plateau of the frozen family (FULL / OOS $ per day, loss bars/day)')
for band in (0.90,0.95,0.98,0.99):
    for th in (-0.01,-0.02,-0.03,-0.05,-0.10):
        m=rule(f,band,th)
        print(f'   ask<{band} dB6<={th}: blk{int(m.sum()):3d} FULL${-f[m].pnl.sum()/10:+6.2f}/d OOS${-f[(~IS)&m].pnl.sum()/3:+6.2f}/d '
              f'lossbars/day {f[~m][lambda x:x.loss==1].bar.nunique()/10:.2f} (base 3.30)')
print('\n=== X. permutation (shuffle F within coin x day), OOS loss-rate diff, 5000 reps')
rng=np.random.default_rng(11); o=f[~IS].copy()
obs=o[o.F].loss.mean()-o[~o.F].loss.mean(); c=0
for _ in range(5000):
    s=o.groupby(['coin','day'],observed=True).F.transform(lambda x: rng.permutation(x.values))
    if (o[s].loss.mean()-o[~s].loss.mean())>=obs: c+=1
print(f'   observed {obs:.4f}  p={c/5000:.4f}')
print('\n=== Y. what the frozen rule blocks, by ask band and clip index')
print(f[f.F].groupby([pd.cut(f[f.F].seen_ask,[0,.55,.8,.9,.95,.98]),'clip'],observed=True)
      .agg(n=('pnl','size'),loss=('loss','sum'),pnl=('pnl','sum')).round(2).to_string())
print('\n=== Z. sanity: is the rule causal-only? columns used =',['seen_ask (bot view at decision)','fav bid now & 6s ago (recorder 10Hz, both pre-decision)'])
