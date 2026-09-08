"""Memory-lean sweep: each worker loads ONE coin once and runs the whole policy list on it."""
import mb, pandas as pd, numpy as np, sys, gc, time
from multiprocessing import Pool
pd.set_option('display.width',260)
POL=[]
def add(lab,**P): POL.append((lab,{**mb.DEF,**P}))
# 1 placement x mode
for pl in ('join','behind','improve','edge05','edge15'):
    for md in ('static','cancel'): add(f'{pl}/{md}',PLACE=pl,MODE=md)
# 2 band 40-60
for pl in ('join','edge15','behind'):
    for md in ('static','cancel'): add(f'{pl}/{md} 40-60',PLACE=pl,MODE=md,QLO=0.40,QHI=0.60)
# 3 size
for sz in (20.,100.):
    add(f'join/cancel size{int(sz)}',PLACE='join',MODE='cancel',SIZE=sz)
    add(f'edge15/static size{int(sz)}',PLACE='edge15',MODE='static',SIZE=sz)
# 4 windows
for lab,lo,hi in [('first60 (240-300)',240.,300.),('first60ex4s (240-296)',240.,296.),('min2 (180-240)',180.,240.),('mid (120-180)',120.,180.),('late (40-120)',40.,120.)]:
    add(f'join/cancel {lab}',PLACE='join',MODE='cancel',TL_LO=lo,TL_HI=hi)
    add(f'edge15/static {lab}',PLACE='edge15',MODE='static',TL_LO=lo,TL_HI=hi)
# 5 placebo / requote
add('join/cancel RAND-side',PLACE='join',MODE='cancel',SIDES='rand')
add('join/cancel U-only',PLACE='join',MODE='cancel',SIDES='U')
add('edge15/static RAND-side',PLACE='edge15',MODE='static',SIDES='rand')
add('join/cancel MAXFILL99',PLACE='join',MODE='cancel',MAXFILL=99)
add('edge15/static MAXFILL99',PLACE='edge15',MODE='static',MAXFILL=99)
# 6 improve into wide spread, hold variants
add('improve3/cancel (spread>=3c)',PLACE='improve3',MODE='cancel')
add('improve3/cancel first60',PLACE='improve3',MODE='cancel',TL_LO=240.,TL_HI=300.)
add('join/static H3',PLACE='join',MODE='static',H=3.)
add('join/static H30',PLACE='join',MODE='static',H=30.)

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
    pd.to_pickle((allF,allB),'sweep_raw.pkl')
    print('done %.0fs'%(time.time()-t0))
