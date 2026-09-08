"""Join every real print to the prevailing 10Hz book (as-of, strictly causal) and
score the MAKER side of it.  Model-free ground truth: every fill in the market."""
import pandas as pd, numpy as np
PQ='pq'
SC=['coin','ws','t','tl','ub','ubs','ua','uas','vol','volsh','lead_bps']
A=[]
for c in ['btc','eth','sol','xrp','bnb','doge','hype']:
    s=pd.read_parquet(f'{PQ}/snapcur.parquet',columns=SC,filters=[('coin','==',c)]).sort_values('t')
    t=pd.read_parquet(f'{PQ}/trades.parquet',filters=[('coin','==',c)]).sort_values('t')
    s['ws']=s.ws.astype('int64')
    t=pd.merge_asof(t,s.drop(columns=['coin','tl']),on='t',by='ws',direction='backward',
                    tolerance=1.0,allow_exact_matches=True)
    A.append(t)
t=pd.concat(A,ignore_index=True)
r=pd.read_parquet(f'{PQ}/res.parquet')[['coin','ws','win']]
t=t.merge(r,on=['coin','ws'],how='inner')
t['tl']=t.ws+300-t.mts
wU=(t.win=='UP').astype(int).values; tokU=(t.tok=='U').values
winTok=np.where(tokU,wU,1-wU)
mkbuy=(t.side=='SELL').values                       # taker sold -> maker BOUGHT that token
t['mq']=np.where(mkbuy,t.px,1-t.px)                 # maker's effective buy price
t['mwin']=np.where(mkbuy,winTok,1-winTok)
# the maker's own-space touch at the time of the print
# maker bought tok T at mq. If T==U -> touch is ub. If T==D -> touch is 1-ua.
mtokU=np.where(mkbuy,tokU,~tokU)
t['mtouch']=np.where(mtokU,t.ub,1-t.ua)
t['mmid']=np.where(mtokU,(t.ub+t.ua)/2,1-(t.ub+t.ua)/2)
t['spr']=(t.ua-t.ub).round(3)
t['attouch']=(t.mq-t.mtouch).abs()<0.0005
t['gross_c']=(t.mwin-t.mq)*100
t['reb_c']=0.2*0.07*t.mq*(1-t.mq)*100
t['net_c']=t.gross_c+t.reb_c
t['edge_c']=(t.mmid-t.mq)*100                       # how far below the mid the maker bought
t['sel_c']=(t.mwin-t.mmid)*100                      # outcome vs the mid at fill
dt=pd.to_datetime(t.ws,unit='s',utc=True)
t['hr']=dt.dt.hour; t['dow']=dt.dt.dayofweek; t['day']=dt.dt.date.astype(str)
t.to_parquet('fieldctx.parquet',index=False)
print(len(t),'prints;  book joined',t.ub.notna().mean().round(4))
