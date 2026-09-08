"""The TRADEABLE subset: tick-jump fills at t >= venue tick_size_change timestamp (0.991 is
rejected before it).  Plus: is the flip a periodic job?"""
import pandas as pd, numpy as np
F=pd.read_parquet('a12_tick.parquet')
print('flip venue-ts mod 60s histogram (10s bins):',np.histogram(F.t_tick%60,bins=6,range=(0,60))[0])
print('flip venue-ts mod 300s (bar) 30s bins:',np.histogram(F.t_tick%300,bins=10,range=(0,300))[0])
print('flip minus close, 20s bins from -120..+120:',np.histogram(F.rel,bins=12,range=(-120,120))[0])
for lab in ('G0','G2','G1G2'):
    d=pd.read_parquet(f'a2_{lab}.parquet'); d['ws']=d.ws.astype('int64')
    d=d.merge(F[['coin','ws','t_tick']],on=['coin','ws'],how='left')
    d['reb']=0.2*0.07*d.q*(1-d.q); d['pnl']=d.f*((d.win-d.q)+d.reb)
    d['ok']=d.t_tick.notna()&(d.t>=d.t_tick+0.2)
    for k,m in [('ALL (as simulated)',np.ones(len(d),bool)),('TRADEABLE: fill after venue flip',d.ok.values)]:
        x=d[m]; bb=x.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'),w=('win','max'))
        ps=bb.p.sum()/bb.s.sum(); se=np.sqrt(((bb.p-ps*bb.s)**2).sum())/bb.s.sum()
        day=x.assign(day=pd.to_datetime(x.ws,unit='s',utc=True).dt.date).groupby('day').pnl.sum()
        loo={c:round(bb.drop(index=c,level=0).p.sum()/6,1) for c in bb.index.get_level_values(0).unique()}
        print(f'{lab:5s} {k:34s} bars {len(bb):5d} sh {int(bb.s.sum()):6d} q {(x.q*x.f).sum()/x.f.sum():.4f} wr {(x.win*x.f).sum()/x.f.sum():.5f} net {ps*100:+.3f}+/-{se*100:.3f} $/d {bb.p.sum()/6:+6.1f} d+ {int((day>0).sum())}/{len(day)} loss bars {int((bb.w==0).sum())} LOO-btc {loo.get("btc",0):+.1f}')
    x=d[d.ok]; print('      tradeable per coin $/6d:',x.groupby('coin').pnl.sum().round(1).to_dict())
    print('      tradeable: fill tl p25/50/75',np.percentile(x.tl,[25,50,75]).round(1),' seconds after flip p25/50/75',np.percentile(x.t-x.t_tick,[25,50,75]).round(1))
