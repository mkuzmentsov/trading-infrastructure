"""Cleaner, price-filtered causal flow features + book drift, on the panel."""
import pandas as pd,numpy as np
t=__import__('lib').load_trades()
pan=pd.read_parquet('pq/panelflow.parquet')
t=t[(t.tl>=0)&(t.tl<=120)].copy(); t['tlk']=np.ceil(t.tl).astype(int)
t['sgn']=np.where(t.side=='BUY',1.0,-1.0)
# information-bearing prints only: ignore the sub-20c lottery tail and the >=0.98 noise
mid=t[(t.px>=0.15)&(t.px<=0.97)].copy()
mid['u']=np.where(mid.tok=='U',mid.sgn*mid.notional,-mid.sgn*mid.notional)
# pure dumping of a rich token (px>=0.5, SELL)
dmp=t[(t.px>=0.5)&(t.side=='SELL')].copy()
dmp['u']=np.where(dmp.tok=='U',-dmp.notional,dmp.notional)
def cube(df,col):
    g=df.groupby(['coin','ws','tlk'])[col].sum().reset_index()
    idx={}
    for (c,ws),h in g.groupby(['coin','ws']):
        a=np.zeros(122); k=h.tlk.values.astype(int); m=(k>=0)&(k<=120)
        a[k[m]]=h[col].values[m]; idx[(c,ws)]=np.concatenate([[0],np.cumsum(a)])
    return idx
I1=cube(mid,'u'); I2=cube(dmp,'u')
coins=pan.coin.values; wss=pan.ws.values; tls=pan.tlk.values.astype(int)
for name,I in (('mf',I1),('dp',I2)):
    for K in (10,30):
        V=np.zeros(len(pan))
        for i in range(len(pan)):
            e=I.get((coins[i],wss[i]))
            if e is None: continue
            a=tls[i]; b=min(a+K,121); V[i]=e[b]-e[a]
        pan[f'{name}{K}']=np.where(pan.side.values=='UP',V,-V)
# book drift: fav bid change over prior 10s
bb=pan[['coin','ws','tlk','fav_bid']].copy()
bb['tlk']=bb.tlk-10
pan=pan.merge(bb.rename(columns={'fav_bid':'fav_bid_10'}),on=['coin','ws','tlk'],how='left')
pan['dbid10']=pan.fav_bid-pan.fav_bid_10
pan.to_parquet('pq/panelflow2.parquet',index=False)
print(pan.shape)
