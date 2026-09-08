import pandas as pd, numpy as np, sys
pd.set_option('display.width',260)
allF,allB=pd.read_pickle(sys.argv[1] if len(sys.argv)>1 else 'sweep_raw.pkl')
DAYS=6.0
def score(F,B,lab):
    r=dict(lab=lab)
    ssb=B.ss_band.sum()/DAYS; ssa=B.ss_all.sum()/DAYS
    if len(F):
        F=F.copy(); F['reb']=0.2*0.07*F.q*(1-F.q); F['pnl']=F.f*((F.win-F.q)+F.reb)
        sh=F.f.sum(); w=lambda x:(x*F.f).sum()/sh
        per=F.groupby(['coin','ws']).agg(p=('pnl','sum'),s=('f','sum'))
        ps=per.p.sum()/sh; se=np.sqrt(((per.p-ps*per.s)**2).sum())/sh
        bs=F.groupby(['coin','ws','side']).agg(f=('f','sum'),win=('win','max'))
        F['day']=pd.to_datetime(F.ws,unit='s',utc=True).dt.date
        F2=F.groupby(['coin','ws','side']).apply(lambda g:(g.q*g.f).sum()/g.f.sum(),include_groups=False).unstack()
        ps_=(F2.U+F2.D).dropna() if ('U' in F2 and 'D' in F2) else pd.Series(dtype=float)
        usd=per.p.sum()/DAYS
        r.update(orders=len(bs),sh_day=round(sh/DAYS),usd_day=round(usd,1),c_sh=round(ps*100,3),se=round(se*100,3),
                 hs=round(w(F.mq-F.q)*100,2),drift=round(w(F.midf-F.mq)*100,2),adv=round(w(F.win-F.midf)*100,2),
                 reb=round(w(F.reb)*100,3),loss_ev=int((bs.win==0).sum()),
                 pair=round((F.groupby(['coin','ws']).side.nunique()==2).mean(),3),
                 pair_sum=round(ps_.mean(),4) if len(ps_) else np.nan,pair_lt1=round((ps_<1).mean(),3) if len(ps_) else np.nan,
                 days_pos=int((F.groupby('day').pnl.sum()>0).sum()),
                 loo_min=round(min(per.drop(index=c,level=0).p.sum()/DAYS for c in per.index.get_level_values(0).unique()),1))
    else:
        r.update(orders=0,sh_day=0,usd_day=0.0,c_sh=np.nan,se=np.nan,hs=np.nan,drift=np.nan,adv=np.nan,reb=np.nan,loss_ev=0,pair=np.nan,pair_sum=np.nan,pair_lt1=np.nan,days_pos=0,loo_min=0)
    r.update(ss_band_k=round(ssb/1000,1),ss_all_k=round(ssa/1000,1),
             usd_per_kss=round(r['usd_day']/(ssb/1000),3) if ssb>0 else np.nan,
             c_per_sh=r['c_sh'])
    return r
rows=[score(allF[l],allB[l],l) for l in allF]
d=pd.DataFrame(rows); d.to_csv('sweep_scored.csv',index=False)
print(d.to_string(index=False))
