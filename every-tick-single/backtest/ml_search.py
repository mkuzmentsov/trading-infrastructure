#!/usr/bin/env python3
"""Large Optuna search over indicators x periods x timeframes x combos x model,
maximizing VALIDATION next-bar AUC — then reports the best config's HELD-OUT TEST
AUC (Optuna never sees test). If exhaustive search finds val 0.56 but test 0.52,
that's search-overfitting; the honest number is test. Anti-overfit by design.

Splits (time-ordered): 60% train / 20% val (Optuna objective) / 20% test (final).
Timeframes via resampling 5m -> {1,3,6,12,24,48} bars. Indicators computed on the
resampled series, aligned back to the base bar (no lookahead).
Usage: python3 ml_search.py <binance_dir> [n_trials=400] [offset=1]
"""
import json, os, sys, math, warnings
import numpy as np
warnings.filterwarnings("ignore")
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score

TFS=[1,3,6,12,24,48]           # 5m,15m,30m,1h,2h,4h
INDS=["smaDist","emaDist","rsi","pctB","bbw","stochK","roc","macd","cci","willr",
      "atrret","adx","donch","volz","mfi","rangez","autocorr","vwapDist"]
PERIODS=[2,3,5,7,10,14,20,30,50,75,100,150,200]

def _sma(a,k):
    out=np.full(len(a),np.nan);cs=np.cumsum(np.insert(a,0,0));out[k-1:]=(cs[k:]-cs[:-k])/k;return out
def _ema(a,k):
    al=2/(k+1);e=np.empty(len(a));e[0]=a[0]
    for i in range(1,len(a)): e[i]=al*a[i]+(1-al)*e[i-1]
    return e
def _roll(a,k,f):
    out=np.full(len(a),np.nan)
    for i in range(k-1,len(a)): out[i]=f(a[i-k+1:i+1])
    return out

def indicator(name,P,o,h,l,c,v):
    with np.errstate(all="ignore"):
        if name=="smaDist": return (c/_sma(c,P)-1)*100
        if name=="emaDist": return (c/_ema(c,P)-1)*100
        if name=="rsi":
            d=np.diff(c,prepend=c[0]);g=_sma(np.where(d>0,d,0),P);ll=_sma(np.where(d<0,-d,0),P)
            return 100-100/(1+g/np.where(ll==0,1e-9,ll))
        if name=="pctB":
            m=_sma(c,P);sd=_roll(c,P,np.std);return (c-(m-2*sd))/(4*np.where(sd==0,1e-9,sd))
        if name=="bbw":
            m=_sma(c,P);sd=_roll(c,P,np.std);return 4*sd/np.where(m==0,1e-9,m)*100
        if name=="stochK":
            lo=_roll(l,P,np.min);hi=_roll(h,P,np.max);return (c-lo)/np.where(hi-lo==0,1e-9,hi-lo)
        if name=="roc": return np.concatenate([np.full(P,np.nan),(c[P:]/c[:-P]-1)*100])
        if name=="macd":
            f=max(2,P//2);return _ema(c,f)-_ema(c,P)
        if name=="cci":
            tp=(h+l+c)/3;m=_sma(tp,P);md=_roll(tp,P,lambda x:np.mean(np.abs(x-x.mean())))
            return (tp-m)/np.where(md==0,1e-9,0.015*md)
        if name=="willr":
            hi=_roll(h,P,np.max);lo=_roll(l,P,np.min);return (hi-c)/np.where(hi-lo==0,1e-9,hi-lo)*-100
        if name=="atrret":
            tr=np.maximum(h-l,np.maximum(np.abs(h-np.roll(c,1)),np.abs(l-np.roll(c,1))));atr=_sma(tr,P)
            return (c-o)/np.where(atr==0,1e-9,atr)
        if name=="adx":
            up=h-np.roll(h,1);dn=np.roll(l,1)-l;pdm=np.where((up>dn)&(up>0),up,0);ndm=np.where((dn>up)&(dn>0),dn,0)
            tr=np.maximum(h-l,np.abs(h-np.roll(c,1)));atr=_sma(tr,P)+1e-9
            pdi=100*_sma(pdm,P)/atr;ndi=100*_sma(ndm,P)/atr;dx=100*np.abs(pdi-ndi)/np.where(pdi+ndi==0,1e-9,pdi+ndi)
            return _sma(dx,P)
        if name=="donch":
            hi=_roll(h,P,np.max);lo=_roll(l,P,np.min);return (c-lo)/np.where(hi-lo==0,1e-9,hi-lo)
        if name=="volz":
            lv=np.log(v+1);return (lv-_sma(lv,P))/np.where(_roll(lv,P,np.std)==0,1e-9,_roll(lv,P,np.std))
        if name=="mfi":
            tp=(h+l+c)/3;mf=tp*v;pos=_sma(np.where(tp>np.roll(tp,1),mf,0),P);neg=_sma(np.where(tp<np.roll(tp,1),mf,0),P)
            return 100-100/(1+pos/np.where(neg==0,1e-9,neg))
        if name=="rangez":
            rg=(h-l)/o*100;return (rg-_sma(rg,P))/np.where(_roll(rg,P,np.std)==0,1e-9,_roll(rg,P,np.std))
        if name=="autocorr":
            r=np.diff(np.log(c),prepend=0);return _roll(r,P,lambda x:np.corrcoef(x[:-1],x[1:])[0,1] if len(x)>2 and x.std()>0 else 0)
        if name=="vwapDist":
            tp=(h+l+c)/3;vw=_sma(tp*v,P)/np.where(_sma(v,P)==0,1e-9,_sma(v,P));return (c-vw)/np.where(vw==0,1e-9,vw)*100
    return np.zeros(len(c))

def resample(o,h,l,c,v,tf):
    if tf==1: return o,h,l,c,v
    n=len(c)//tf*tf
    o=o[:n].reshape(-1,tf);h=h[:n].reshape(-1,tf);l=l[:n].reshape(-1,tf);c=c[:n].reshape(-1,tf);v=v[:n].reshape(-1,tf)
    return o[:,0],h.max(1),l.min(1),c[:,-1],v.sum(1)

def build_feature(S,name,P,tf,N):
    """Full aligned arrays over all (coin,bar) in fixed order; NaN where invalid,
    so any (name,P,tf) returns SAME length + SAME y (combinable)."""
    vals=[];ys=[]
    for coin,(o,h,l,c,v) in S.items():
        ro,rh,rl,rc,rv=resample(o,h,l,c,v,tf)
        f=indicator(name,P,ro,rh,rl,rc,rv)
        for i in range(210,len(c)-N):
            ri=i//tf-1
            vals.append(f[ri] if 0<=ri<len(f) else np.nan)
            tb=i-1+N;ys.append(1 if c[tb]>=o[tb] else 0)
    return np.array(vals,float),np.array(ys)

def main():
    bdir=sys.argv[1];NT=int(sys.argv[2]) if len(sys.argv)>2 else 400;N=int(sys.argv[3]) if len(sys.argv)>3 else 1;SEED=int(sys.argv[4]) if len(sys.argv)>4 else 1
    S={}
    for coin in ("btc","eth","sol","xrp"):
        rows=json.load(open(os.path.join(bdir,f"{coin}_5m.json")))
        S[coin]=tuple(np.array([r[k] for r in rows]) for k in (1,2,3,4,5))
    cache={}
    def feat(name,P,tf):
        key=(name,P,tf)
        if key not in cache: cache[key]=build_feature(S,name,P,tf,N)
        return cache[key]

    def objective(trial):
        k=trial.suggest_int("k",1,3)  # 1-3 indicators combined
        cols=[];y=None
        for j in range(k):
            nm=trial.suggest_categorical(f"ind{j}",INDS)
            P=trial.suggest_categorical(f"P{j}",PERIODS)
            tf=trial.suggest_categorical(f"tf{j}",TFS)
            X,yy=feat(nm,P,tf);cols.append(X);y=yy
        Xm=np.column_stack(cols)
        mask=np.all(np.isfinite(Xm),axis=1)
        Xm=Xm[mask];y=y[mask]
        if len(y)<2000: return 0.5
        model=trial.suggest_categorical("model",["logistic","gbm"])
        n=len(y);a=int(n*.6);b=int(n*.8)
        sc=StandardScaler().fit(Xm[:a]);Xs=sc.transform(Xm)
        if model=="logistic":
            C=trial.suggest_float("C",0.01,2,log=True);clf=LogisticRegression(max_iter=500,C=C)
        else:
            clf=GradientBoostingClassifier(n_estimators=trial.suggest_int("ne",40,120),
                 max_depth=trial.suggest_int("md",2,4),learning_rate=trial.suggest_float("lr",.02,.1,log=True))
        clf.fit(Xs[:a],y[:a])
        vauc=roc_auc_score(y[a:b],clf.predict_proba(Xs[a:b])[:,1])
        trial.set_user_attr("test_auc",roc_auc_score(y[b:],clf.predict_proba(Xs[b:])[:,1]))
        trial.set_user_attr("train_auc",roc_auc_score(y[:a],clf.predict_proba(Xs[:a])[:,1]))
        return vauc

    study=optuna.create_study(direction="maximize",sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective,n_trials=NT,show_progress_bar=False)
    bt=study.best_trial
    print(f"SEED{SEED} val {bt.value:.4f} test {bt.user_attrs['test_auc']:.4f} train {bt.user_attrs['train_auc']:.4f} cfg {[(bt.params.get(f'ind{j}'),bt.params.get(f'P{j}'),bt.params.get(f'tf{j}')) for j in range(bt.params.get('k',1))]}")
    return
    print(f"=== Optuna: {NT} trials, offset +{N} ===")
    print(f"BEST validation AUC = {bt.value:.4f}")
    print(f"  its HELD-OUT TEST AUC = {bt.user_attrs['test_auc']:.4f}  (train {bt.user_attrs['train_auc']:.4f})")
    print(f"  config: {bt.params}")
    top=sorted(study.trials,key=lambda t:t.value or 0,reverse=True)[:8]
    print("\ntop-8 trials (val / test / train):")
    for t in top:
        print(f"  val {t.value:.4f}  test {t.user_attrs.get('test_auc',0):.4f}  train {t.user_attrs.get('train_auc',0):.4f}  {[(t.params.get(f'ind{j}'),t.params.get(f'P{j}'),t.params.get(f'tf{j}')) for j in range(t.params.get('k',1))]}")
    vt=[(t.value,t.user_attrs.get('test_auc',0)) for t in study.trials if t.value]
    print(f"\nacross all trials: best val={max(v for v,_ in vt):.4f}  |  best test={max(tt for _,tt in vt):.4f}  |  mean test={np.mean([tt for _,tt in vt]):.4f}")

if __name__=="__main__": main()
