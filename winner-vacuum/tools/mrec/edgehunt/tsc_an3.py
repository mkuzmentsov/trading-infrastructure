"""Lead 1a, corrected: window rows must match BOTH tok and ws (cur and post markets share token labels)."""
import pandas as pd,numpy as np,json,pyarrow.parquet as pq,pyarrow.compute as pc
T=pd.read_parquet('tsc.parquet'); T['tl']=T.ws+300-T.mts
res=pd.read_parquet('pq/res.parquet'); res['winT']=np.where(res.win=='UP','U','D')
T=T.merge(res[['coin','ws','winT']],on=['coin','ws'],how='left')
def top(a,b):
    bb=json.loads(a); aa=json.loads(b); return (bb[-1][0] if bb else np.nan, aa[0][0] if aa else np.nan, bb[-1][1] if bb else 0, aa[0][1] if aa else 0)
out=[]
for coin in ['btc','eth','sol','xrp','bnb','doge','hype']:
    W=pq.read_table('tsc_win.parquet',filters=[('coin','==',coin),('kind','!=','pc')],columns=['ws','tok','t','kind','a','b','tsc_t','tsc_tok','tsc_ws']).to_pandas()
    W=W[(W.tok==W.tsc_tok)&(W.ws==W.tsc_ws)].sort_values('t')
    Tc=T[T.coin==coin].drop_duplicates(['t','tok']).set_index(['t','tok']).sort_index()
    for (tt,tok),w in W.groupby(['tsc_t','tsc_tok'],sort=False):
        try: r=Tc.loc[(tt,tok)]
        except KeyError: continue
        bk=w[w.kind=='book']; pre=bk[bk.t<tt]; post=bk[(bk.t>=tt)&(bk.t<=tt+5)]
        pb,pa,pbs,pas=top(pre.iloc[-1].a,pre.iloc[-1].b) if len(pre) else (np.nan,np.nan,0,0)
        pt=[top(x.a,x.b) for x in post.itertuples()]
        ncross=sum(1 for b,a,_,__ in pt if b==b and a==a and b>=a-1e-9)
        nfine=sum(1 for b,a,_,__ in pt if (b==b and round(b*1000)%10) or (a==a and round(a*1000)%10))
        tr=w[(w.kind=='trade')&(w.t>=tt)&(w.t<=tt+5)]; pp=[json.loads(x) for x in tr.a]
        out.append(dict(coin=coin,ws=r.ws,tok=tok,tl=r.tl,isw=(tok==r.winT),old=r.old,new=r.new,pre_b=pb,pre_a=pa,pre_bs=pbs,pre_as=pas,
            n_post=len(pt),n_cross=ncross,n_fine=nfine,n_prints=len(pp),sh=sum(float(x[1]) for x in pp),
            n_above_ask=sum(1 for px,sz,sd in pp if pa==pa and float(px)>pa+1e-9 and sd=='BUY'),
            sh_above_ask=sum(float(sz) for px,sz,sd in pp if pa==pa and float(px)>pa+1e-9 and sd=='BUY'),
            n_below_bid=sum(1 for px,sz,sd in pp if pb==pb and float(px)<pb-1e-9 and sd=='SELL'),
            fpb=pt[0][0] if pt else np.nan,fpa=pt[0][1] if pt else np.nan,dt_first_book=(post.t.iloc[0]-tt) if len(post) else np.nan))
    print(coin,len(out),flush=True)
d=pd.DataFrame(out); d.to_parquet('tsc_an.parquet',index=False)
x=d[d.new=='0.001']
print('\nTSC 0.01->0.001 analysed',len(x),' in-bar',(x.tl>0).sum(),' post-close',(x.tl<=0).sum())
print('pre-tsc best bid:',x.pre_b.round(3).value_counts().head(8).to_dict())
print('pre-tsc best ask:',x.pre_a.round(3).value_counts().head(8).to_dict())
print('first post-tsc bid:',x.fpb.round(3).value_counts().head(6).to_dict(),' ask:',x.fpa.round(3).value_counts().head(6).to_dict())
print('crossed/locked within 5s: events',(x.n_cross>0).sum(),'/',len(x))
print('fine-grid level within 5s:',(x.n_fine>0).mean().round(3))
print('prints in 5s:',x.n_prints.sum(),' BUY above pre-ask:',x.n_above_ask.sum(),'(',round(x.sh_above_ask.sum()),'sh)',' SELL below pre-bid:',x.n_below_bid.sum())
ib=x[x.tl>0]; print('IN-BAR: n',len(ib),' tl dist',pd.cut(ib.tl,[0,10,20,30,60,120,300]).value_counts().sort_index().to_dict())
print('IN-BAR pre bid/ask:',ib.pre_b.round(2).value_counts().head(5).to_dict(),ib.pre_a.round(2).value_counts().head(5).to_dict())
print('IN-BAR crossed',(ib.n_cross>0).sum(),' prints',ib.n_prints.sum(),' above-ask',ib.n_above_ask.sum(),'(',round(ib.sh_above_ask.sum()),'sh)',' below-bid',ib.n_below_bid.sum())
print('IN-BAR: which token gets the fine tick — winner?',ib.isw.mean().round(3),' pre_b>=0.9:',(ib.pre_b>=0.9).mean().round(3),' pre_b<=0.1:',(ib.pre_b<=0.1).mean().round(3))
print('dt first book after tsc (s):',x.dt_first_book.describe().round(3).to_dict())
print('\nrevert 0.001->0.01 (n=%d): tl'%(d.new=='0.01').sum(), d[d.new=='0.01'].tl.round(1).tolist()[:10], 'pre_b',d[d.new=='0.01'].pre_b.round(2).tolist()[:10])
