"""Fate of a winner-side ask observed at tl=T0: traded away, cancelled, or still
there at tl=T1 — measured against the real print tape."""
import pandas as pd,numpy as np
pd.set_option('display.width',250)
t=__import__('lib').load_trades()
pan=pd.read_parquet('pq/panel.parquet').rename(columns={'cov':'covg'})
pan=pan[pan.est_bps.notna()]

def fate(T0,T1,askcap=0.99,minsz=8.0,minest=0.5):
    a=pan[(pan.tlk==T0)&(pan.covg>=0.5)&(pan.est_bps.abs()>=minest)
          &(pan.fav_ask.notna())&(pan.fav_ask<=askcap)&(pan.fav_asz>=minsz)].copy()
    b=pan[pan.tlk==T1][['coin','ws','fav_ask','fav_asz','side']].rename(
        columns={'fav_ask':'ask1','fav_asz':'asz1','side':'side1'})
    a=a.merge(b,on=['coin','ws'],how='left')
    # prints on the same token between T0 and T1 at price >= ask-0.005 (the level got lifted)
    tk=t[(t.tl<=T0)&(t.tl>T1)].copy()
    tk['favtok']=np.where(tk.tok=='U','UP','DOWN')
    key=['coin','ws']
    a['k']=list(zip(a.coin,a.ws))
    tk['k']=list(zip(tk.coin,tk.ws))
    sub=tk.set_index('k')
    out=[]
    for r in a.itertuples():
        try: g=sub.loc[[r.k]]
        except KeyError: g=None
        lifted=0.0; lifted_at=np.nan
        if g is not None and len(g):
            g=g[(g.favtok==r.side)&(g.side=='BUY')&(g.px>=r.fav_ask-0.005)]
            lifted=float((g.px*g.sz).sum())
            if len(g): lifted_at=float(g.px.mean())
        out.append((lifted,lifted_at))
    a[['lifted$','lift_px']]=pd.DataFrame(out,index=a.index)
    a['still']=(a.ask1.notna())&(a.side1==a.side)&(a.ask1<=askcap)
    a['top$']=a.fav_ask*a.fav_asz
    a['traded']=a['lifted$']>0.5
    return a

for (T0,T1) in [(18,13),(20,14),(25,14),(30,20)]:
    a=fate(T0,T1)
    n=len(a)
    print(f'--- winner-side ask<=0.99 (>= 8sh, |est|>=0.5, cov>=0.5) at tl={T0}, fate by tl={T1}: n={n} bars')
    print(f'   still displayed at tl={T1}: {a.still.mean():.1%} | any lift-print in ({T1},{T0}]: {a.traded.mean():.1%}')
    x=a.groupby(['still','traded']).agg(n=('top$','size'),win=('right','mean'),medtop=('top$','median'),medlift=('lifted$','median')).round(3)
    print(x)
    print(f'   win% of bars whose ask VANISHED-uncrossed (cancelled): {a[(~a.still)&(~a.traded)].right.mean():.4f}  n={((~a.still)&(~a.traded)).sum()}')
    print(f'   win% of bars whose ask was TRADED away          : {a[a.traded].right.mean():.4f}  n={a.traded.sum()}')
    print(f'   win% of bars whose ask PERSISTED                : {a[a.still].right.mean():.4f}  n={a.still.sum()}')
    print()
