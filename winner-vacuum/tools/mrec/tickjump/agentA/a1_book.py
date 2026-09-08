"""Lead 1a/1b: hidden-queue + competitive-response, from the EVENT-level book (bookev) and tape.
Token-native: for the favourite token F (b0>=0.98, tl 2-30):
  sell pressure on F = SELL prints on F (hit F.b0) + BUY prints on the other token at 1-b0 (same level).
1a: is the print size <= displayed b0s?  does b0s drop by ~sz right after?  (if yes, the taker consumed
    the displayed level => an order at b0+0.001 would have been hit first, by price priority)
1b: how often does F.b0 IMPROVE (rise) inside tl 2-30, by how much, with what size, and how long does a
    fresh best-bid level survive before someone improves on it?"""
import pandas as pd, numpy as np
COINS=['btc','eth','sol','xrp','bnb','doge','hype']
r=pd.read_parquet('pq/res.parquet')
R1=[];R2=[];R3=[]
for c in COINS:
    b=pd.read_parquet('pq/bookev.parquet',filters=[('coin','==',c)]).sort_values(['tok','ws','t'])
    t=pd.read_parquet('pq/trades.parquet',filters=[('coin','==',c)])
    b['tl']=b.ws+300-b.t; t['tl']=t.ws+300-t.mts
    b=b[(b.tl>=0)&(b.tl<=40)]; t=t[(t.tl>=2)&(t.tl<=30)]
    for tok in ('U','D'):
        opp='D' if tok=='U' else 'U'
        bt=b[b.tok==tok].astype({'ws':'int64'}).sort_values('t')
        # sell pressure on tok, in tok space
        s1=t[(t.tok==tok)&(t.side=='SELL')][['ws','mts','px','sz']]
        s2=t[(t.tok==opp)&(t.side=='BUY')][['ws','mts','px','sz']].assign(px=lambda d:1-d.px)
        s=pd.concat([s1,s2]).astype({'ws':'int64'}).rename(columns={'mts':'t'}).sort_values('t')
        s['px']=s.px.round(3)
        m=pd.merge_asof(s,bt[['ws','t','b0','b0s']],on='t',by='ws',direction='backward',tolerance=2.0,allow_exact_matches=False)
        # next book event after the print
        nb=bt[['ws','t','b0','b0s']].rename(columns={'b0':'b0n','b0s':'b0sn','t':'tn'})
        m=pd.merge_asof(m.sort_values('t'),nb.assign(t=nb.tn),on='t',by='ws',direction='forward',tolerance=2.0,allow_exact_matches=False)
        m=m[(m.b0>=0.98)&m.b0.notna()]
        m['atb']=np.isclose(m.px,m.b0,atol=1e-6); m['above']=m.px>m.b0+1e-6; m['below']=m.px<m.b0-1e-6
        m['fits']=m.sz<=m.b0s+1e-6
        m['dec']=(m.b0sn-m.b0s); m['sameL']=np.isclose(m.b0n,m.b0,atol=1e-6)
        m['coin']=c;m['tok']=tok
        R1.append(m)
        # 1b improvements of b0
        bt2=bt[(bt.tl>=2)&(bt.tl<=30)&(bt.b0>=0.98)].copy()
        bt2['db0']=bt2.groupby('ws').b0.diff(); bt2['dt']=bt2.groupby('ws').t.diff()
        imp=bt2[bt2.db0>1e-6].copy(); imp['coin']=c;imp['tok']=tok
        # time until the NEXT improvement in the same bar
        imp['t_next']=imp.groupby('ws').t.shift(-1); imp['gap']=imp.t_next-imp.t
        R2.append(imp[['coin','tok','ws','tl','t','b0','b0s','db0','gap']])
        bars=bt2.groupby('ws').agg(n_ev=('t','size'),secs=('t',lambda x:x.max()-x.min()))
        bars['coin']=c;bars['tok']=tok; R3.append(bars)
m=pd.concat(R1,ignore_index=True); imp=pd.concat(R2,ignore_index=True); bars=pd.concat(R3)
sh=m.sz.sum()
print(f'=== 1a HIDDEN QUEUE: prints of sell pressure on a fav token with b0>=0.98, tl 2-30: n={len(m)} sh={int(sh)}')
for k in ('atb','above','below'):
    x=m[m[k]]; print(f'  {k:6s} prints {len(x)/len(m)*100:5.2f}%  shares {x.sz.sum()/sh*100:5.2f}%')
a=m[m['atb']]
print(f'  AT-best-bid prints: size<=displayed b0s: {a.fits.mean()*100:.1f}% of prints, {a.sz[a.fits].sum()/a.sz.sum()*100:.1f}% of shares')
print(f'  AT-best-bid prints: next book event keeps the level: {a.sameL.mean()*100:.1f}%; median displayed b0s {a.b0s.median():.0f}, median print sz {a.sz.median():.0f}')
ok=a[a.sameL]; print(f'  where level kept: displayed size change after print vs -sz: corr {np.corrcoef(ok.dec,-ok.sz)[0,1]:.3f}; median(dec+sz) {np.median(ok.dec+ok.sz):.1f}')
print(f'  print sz > displayed (hidden/refresh) shares share: {a.sz[~a.fits].sum()/a.sz.sum()*100:.1f}%')
print(f'\n=== 1b COMPETITIVE RESPONSE: best-bid IMPROVEMENTS on fav token (b0>=0.98) inside tl 2-30 ===')
nb=len(bars); print(f'  bar-tokens observed {nb}; improvements {len(imp)} => {len(imp)/nb:.3f} per bar-token; by size of jump (0.001 ticks):')
print((np.round(imp.db0*1000)).clip(upper=10).value_counts().sort_index().to_string())
print(f'  size of the NEW best level at improvement: p25 {imp.b0s.quantile(.25):.0f} p50 {imp.b0s.median():.0f} p75 {imp.b0s.quantile(.75):.0f}')
one=imp[np.isclose(imp.db0,0.001,atol=1e-4)]
print(f'  exactly +0.001 improvements: {len(one)} ({len(one)/nb:.3f}/bar-token); size p50 {one.b0s.median():.0f}; per coin:')
print(one.groupby('coin').size().to_string())
print(f'  time until NEXT improvement in same bar (all improvements): p50 {imp.gap.median():.2f}s, share <1s {(imp.gap<1).mean()*100:.1f}%, no further {(imp.gap.isna()).mean()*100:.1f}%')
# fraction of late-window time where b0 is off the 0.01 grid (someone already sits at a 0.001 level)
m2=m.copy(); m2['off']=(np.round(m2.b0*1000)%10)!=0
print(f'\n  sell-pressure prints arriving when the best bid is ALREADY off-grid (0.001 level): {m2.off.mean()*100:.1f}% prints, {m2.sz[m2.off].sum()/sh*100:.1f}% shares')
print(m2.groupby('coin').off.mean().round(3).to_string())
m.to_parquet('a1_prints.parquet',index=False); imp.to_parquet('a1_imp.parquet',index=False)
