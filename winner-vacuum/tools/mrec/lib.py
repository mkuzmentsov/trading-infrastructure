import os
import pandas as pd, numpy as np
PQ=os.environ.get('MREC_PQ', 'pq')
def load_trades():
    t=pd.read_parquet(f'{PQ}/trades.parquet')
    r=pd.read_parquet(f'{PQ}/res.parquet'); r['winT']=np.where(r.win=='UP','U','D')
    t=t.merge(r[['coin','ws','winT']],on=['coin','ws'],how='inner')
    t['tl']=t.ws+300-t.mts
    t['isw']=(t.tok==t.winT)
    t['notional']=t.px*t.sz
    t['fee']=t.sz*0.07*t.px*(1-t.px)            # taker fee, crypto rate 0.07
    t['gross']=np.where(t.isw,(1-t.px)*t.sz,-t.px*t.sz)
    t['net']=t.gross-t.fee
    t['hr']=pd.to_datetime(t.ws,unit='s',utc=True).dt.hour
    t['day']=pd.to_datetime(t.ws,unit='s',utc=True).dt.date
    return t
def tab(df,by,minn=0):
    g=df.groupby(by,observed=True).agg(n=('px','size'),sh=('sz','sum'),notl=('notional','sum'),
        gross=('gross','sum'),fee=('fee','sum'),net=('net','sum'),wr=('isw','mean'))
    g['groi%']=g.gross/g.notl*100; g['nroi%']=g.net/g.notl*100
    return g[g.n>=minn].round(3)
