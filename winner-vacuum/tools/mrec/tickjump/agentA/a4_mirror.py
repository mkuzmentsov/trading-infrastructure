"""Lead 2: the MIRROR LOTTERY - a resting bid at 0.001-0.009 on the UNDERDOG in the last 30s
(== an ask on the favourite at 0.991-0.999).  Steps: (i) does the 0.001 grid exist below 0.04?
(ii) displayed queue at those levels (lad10, tl<=26); (iii) taker sell pressure on the underdog at
<= 0.009 (tape); (iv) terminal PnL, events not t-stats."""
import mm, pandas as pd, numpy as np
COINS=mm.COINS
s=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','tl','ub','db','ubs','dbs','ua','da'])
s=s[s.tl.between(0,30)]
print('=== (i) grid below 0.04, tl 0-30: third-decimal digit of the UNDERDOG best bid ===')
for col in ('ub','db'):
    x=s[(s[col]>0)&(s[col]<0.04)][col]
    print(f'{col}: n={len(x)}  off-0.01-grid share {((np.round(x*1000)%10)!=0).mean()*100:.2f}%  value counts:'); print(np.round(x,3).value_counts().head(8).to_string())
und=np.where(s.ub<=s.db,'U','D'); ubid=np.where(und=='U',s.ub,s.db); ubs=np.where(und=='U',s.ubs,s.dbs)
u=pd.DataFrame({'coin':s.coin,'ws':s.ws,'tl':s.tl,'tok':und,'bid':ubid,'bsz':ubs})
print('\nunderdog best bid when fav bid>=0.98:'); f=s[np.maximum(s.ub,s.db)>=0.98]
ub2=np.where(f.ub<=f.db,f.ub,f.db); print(pd.Series(np.round(ub2,3)).value_counts(dropna=False).head(8).to_string())
print('underdog best-bid displayed size at 0.001-0.009: p25/50/75',np.nanpercentile(u.bsz[(u.bid>=0.001)&(u.bid<=0.009)],[25,50,75]))
del s
# (ii) ladder
L=pd.read_parquet('lad10.parquet'); L=L[L.tl.between(2,26)]
rows=[]
for tok,pre in (('U','ubd'),('D','dbd')):
    ps=[L[f'{pre}{i}p'] for i in range(10)]; ss=[L[f'{pre}{i}s'] for i in range(10)]
    P=np.vstack([p.values for p in ps]).T; S=np.vstack([x.values for x in ss]).T
    isund=(L.ubd0p<=L.dbd0p) if tok=='U' else (L.dbd0p<L.ubd0p)
    P=P[isund.values]; S=S[isund.values]
    for lo,hi in [(0.0005,0.0015),(0.0015,0.0055),(0.0055,0.0095),(0.0095,0.0105),(0.0105,0.02)]:
        m=(P>=lo)&(P<hi); tot=np.where(m,S,0).sum(1)
        rows.append(dict(tok=tok,band=f'{lo:.4f}-{hi:.4f}',snaps=len(P),share_with_level=round(m.any(1).mean()*100,1),median_sz_when_present=float(np.median(tot[tot>0])) if (tot>0).any() else 0))
print('\n=== (ii) displayed UNDERDOG bid ladder, tl 2-26 (lad10) ==='); print(pd.DataFrame(rows).to_string(index=False))
# (iii) taker sell pressure on the underdog at <= 0.009, tl 2-30
r=pd.read_parquet('pq/res.parquet'); r['winT']=np.where(r.win=='UP','U','D')
t=pd.read_parquet('pq/trades.parquet'); t=t.merge(r[['coin','ws','winT']],on=['coin','ws']); t['tl']=t.ws+300-t.mts
opp={'U':'D','D':'U'}
a=t[t.side=='SELL'][['coin','ws','tok','px','sz','tl','winT','t']].copy()
b=t[t.side=='BUY'][['coin','ws','tok','px','sz','tl','winT','t']].copy(); b['tok']=b.tok.map(opp); b['px']=1-b.px
p=pd.concat([a,b]); p=p[p.tl.between(2,30)]; p['px']=p.px.round(3)
und=p[p.px<=0.0095]
print(f'\n=== (iii) taker SELL pressure at <=0.009 in tl 2-30 (== BUYS of the favourite at >=0.991): prints {len(und)} sh {int(und.sz.sum())} ({und.sz.sum()/6:.0f}/day) ===')
print(und.groupby(np.round(und.px,3)).agg(n=('sz','size'),sh=('sz','sum'),win=('tok',lambda x:0)).to_string())
und['isw']=(und.tok==und.winT)
print('share-weighted P(underdog token wins | such a print):',round((und.sz*und.isw).sum()/und.sz.sum(),5),'  n winning prints',int(und.isw.sum()))
print('per coin sh/day:',(und.groupby('coin').sz.sum()/6).round(0).to_dict())
# (iv) sim: rest a bid on the underdog at best_bid+0.001 (or 0.001 if no bid), fill from pressure at <= q, ahead=0
sn=pd.read_parquet('pq/snapcur.parquet',columns=['coin','ws','t','tl','ub','db','ua','da','evage'])
sn=sn[sn.tl.between(2,30)&(sn.evage<1)].sort_values(['coin','ws','t'])
out=[]
for (c,ws),g in sn.groupby(['coin','ws']):
    if c not in COINS: continue
    pp=p[(p.coin==c)&(p.ws==ws)]
    for tok in ('U','D'):
        bid=g.ub if tok=='U' else g.db; ask=g.ua if tok=='U' else g.da
        # underdog only: the other side's bid >=0.98
        oth=g.db if tok=='U' else g.ub
        ok=(oth>=0.98)
        if not ok.any(): continue
        gg=g[ok]; b0=bid[ok].fillna(0.0)
        q=np.round(np.minimum(b0+0.001,0.0095),4)   # cap at 0.0095 so we never pay >= 0.01
        # use the median quote over the window as the resting price (re-quote ignored: q barely moves)
        qq=float(np.median(q)); t0=gg.t.iloc[0]
        x=pp[(pp.tok==tok)&(pp.px<=qq+1e-9)&(pp.t>=t0+0.2)]
        f=min(50.0,x.sz.sum())
        if f>0:
            w=r[(r.coin==c)&(r.ws==ws)].winT.iloc[0]==tok
            out.append(dict(coin=c,ws=ws,tok=tok,q=qq,f=f,win=int(w)))
d=pd.DataFrame(out)
if len(d):
    d['pnl']=d.f*((d.win-d.q)+0.2*0.07*d.q*(1-d.q))
    print(f'\n=== (iv) UNDERDOG resting bid, tl 2-30, q=bid+0.001 (<=0.0095), 50sh cap: filled bars {len(d)} sh {int(d.f.sum())} mean q {(d.q*d.f).sum()/d.f.sum():.4f} WIN EVENTS {int(d.win.sum())} pnl ${d.pnl.sum():.2f} (${d.pnl.sum()/6:.2f}/day)')
    print('  break-even win rate = q =',round((d.q*d.f).sum()/d.f.sum(),4),' observed',round((d.win*d.f).sum()/d.f.sum(),5))
    print(d[d.win==1].to_string(index=False))
    print(d.groupby('coin').agg(bars=('ws','size'),sh=('f','sum'),wins=('win','sum'),pnl=('pnl','sum')).round(2).to_string())
else: print('no fills')
