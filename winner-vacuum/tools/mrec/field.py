"""MODEL-FREE: what the average MAKER fill earns, straight from the print tape.
Every print has a maker on the other side.  Taker BUY tok @px  -> maker SOLD tok  @px
                                            Taker SELL tok @px -> maker BOUGHT tok @px
A maker SELL of tok at px == a maker BUY of the OTHER token at 1-px (one book).
So every print is a maker BUY of some token at some price q -> payoff (win_that_token - q).
"""
import pandas as pd, numpy as np
PQ='pq'
t=pd.read_parquet(f'{PQ}/trades.parquet')
r=pd.read_parquet(f'{PQ}/res.parquet')[['coin','ws','win']]
t=t.merge(r,on=['coin','ws'],how='inner')
t['tl']=t.ws+300-t.mts
wU=(t.win=='UP').astype(int)
tokU=(t.tok=='U')
winTok=np.where(tokU,wU,1-wU)                 # did the printed token win
# maker side
mk_buy = (t.side=='SELL')                     # taker sold -> maker bought that token
t['mq']  = np.where(mk_buy, t.px, 1-t.px)                 # maker's effective BUY price
t['mwin']= np.where(mk_buy, winTok, 1-winTok)             # did the maker's token win
t['gross_c']=(t.mwin-t.mq)*100
t['reb_c']=0.2*0.07*t.mq*(1-t.mq)*100
t['net_c']=t.gross_c+t.reb_c
t['day']=pd.to_datetime(t.ws,unit='s',utc=True).dt.date.astype(str)
t['hr']=pd.to_datetime(t.ws,unit='s',utc=True).dt.hour
