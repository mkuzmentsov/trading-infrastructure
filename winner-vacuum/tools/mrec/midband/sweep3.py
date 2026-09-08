"""Memory-lean sweep: each worker loads ONE coin once and runs the whole policy list on it."""
import mb, pandas as pd, numpy as np, sys, gc, time
from multiprocessing import Pool
pd.set_option('display.width',260)
POL=[]
def add(lab,**P): POL.append((lab,{**mb.DEF,**P}))
add('join/cancel first60',PLACE='join',MODE='cancel',TL_LO=240.,TL_HI=300.)
add('improve3/cancel first60',PLACE='improve3',MODE='cancel',TL_LO=240.,TL_HI=300.)
add('join/cancel first60 40-60',PLACE='join',MODE='cancel',TL_LO=240.,TL_HI=300.,QLO=0.40,QHI=0.60)
add('improve3/cancel first60 40-60',PLACE='improve3',MODE='cancel',TL_LO=240.,TL_HI=300.,QLO=0.40,QHI=0.60)
add('edge05/cancel first60',PLACE='edge05',MODE='cancel',TL_LO=240.,TL_HI=300.)
add('join/cancel LAT0.1',PLACE='join',MODE='cancel',LAT=0.1)
add('join/cancel LAT0.4',PLACE='join',MODE='cancel',LAT=0.4)
add('join/cancel first60 LAT0.4',PLACE='join',MODE='cancel',TL_LO=240.,TL_HI=300.,LAT=0.4)
add('improve3/cancel first60 size20',PLACE='improve3',MODE='cancel',TL_LO=240.,TL_HI=300.,SIZE=20.)
def work(coin):
    s,t,res=mb.load_coin(coin)
    winmap={ws:(1 if w=='UP' else 0) for ws,w in zip(res.ws.values,res.win.values)}
    S=mb.bidx(s.ws.values); T=mb.bidx(t.ws.values)
    st,stl,ub,ua,ev=s.t.values,s.tl.values,s.ub.values,s.ua.values,s.evage.values
    LBP=[s[f'ubd{i}p'].values for i in range(3)]; LBS=[s[f'ubd{i}s'].values for i in range(3)]
    LAP=[s[f'uad{i}p'].values for i in range(3)]; LAS=[s[f'uad{i}s'].values for i in range(3)]
    Tt,Tp,Tsz,Tsl=t.t.values,t.pU.values,t.sz.values,t.sellp.values
    del s,t; gc.collect()
    out={}
    for lab,P in POL:
        rng=np.random.default_rng(hash(coin)%2**32); F=[]; B=[]
        for ws,(a,b) in S.items():
            if ws not in winmap: continue
            wU=winmap[ws]; ta,tb=T.get(ws,(0,0))
            sides=('U','D') if P['SIDES']=='both' else ((P['SIDES'],) if P['SIDES'] in ('U','D') else (rng.choice(['U','D']),))
            sst=st[a:b]; smid=(ub[a:b]+ua[a:b])/2
            for side in sides:
                if side=='U':
                    bb,ba=ub[a:b],ua[a:b]; lp=[x[a:b] for x in LBP]; ls=[x[a:b] for x in LBS]
                    tp=Tp[ta:tb]; tsl=Tsl[ta:tb]; win=wU
                else:
                    bb,ba=1.0-ua[a:b],1.0-ub[a:b]; lp=[1.0-x[a:b] for x in LAP]; ls=[x[a:b] for x in LAS]
                    tp=1.0-Tp[ta:tb]; tsl=~Tsl[ta:tb]; win=1-wU
                fl,ssb,ssa,npl=mb.bar_sim(side,sst,stl[a:b],bb,ba,lp,ls,ev[a:b],Tt[ta:tb],tp,Tsz[ta:tb],tsl,win,P)
                for d in fl:
                    jj=np.searchsorted(sst,d['tf'],'right')-1
                    m2=smid[max(jj,0)]; d['midf']=m2 if side=='U' else 1-m2
                    d.update(coin=coin,ws=ws,side=side); F.append(d)
                B.append(dict(coin=coin,ws=ws,side=side,ss_band=ssb,ss_all=ssa,nplace=npl,nfill=len(fl)))
        out[lab]=(pd.DataFrame(F),pd.DataFrame(B))
        print(coin,lab,len(F),flush=True,file=sys.stderr)
    return coin,out

if __name__=='__main__':
    t0=time.time()
    with Pool(2) as pool: R=pool.map(work,mb.COINS)
    allF={lab:pd.concat([r[1][lab][0] for r in R],ignore_index=True) for lab,_ in POL}
    allB={lab:pd.concat([r[1][lab][1] for r in R],ignore_index=True) for lab,_ in POL}
    pd.to_pickle((allF,allB),'sweep_raw2.pkl')
    print('done %.0fs'%(time.time()-t0))
