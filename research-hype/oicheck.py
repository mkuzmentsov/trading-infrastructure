#!/usr/bin/env python3
"""/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/research-hype/oicheck.py
The carry's main risk is that funding keeps compressing. Does OPEN INTEREST
(a crowding proxy, 21 months hourly from Bybit) predict funding? Strictly
causal: OI known at t predicts funding over (t, t+H]. Placebo included."""
import numpy as np, pandas as pd
H="/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/hl-hist"
oi=pd.read_parquet(f"{H}/bybit/oi/HYPEUSDT-1h.parquet").sort_values("time").rename(columns={"time":"t"})
fu=pd.read_parquet(f"{H}/funding/HYPE.parquet").sort_values("time").rename(columns={"time":"t"})
fu["t"]=(fu.t//3600000)*3600000; oi["t"]=(oi.t//3600000)*3600000
d=fu.groupby("t").fundingRate.mean().to_frame().join(oi.groupby("t").openInterest.mean(),how="inner").reset_index()
d["dt"]=pd.to_datetime(d.t,unit="ms",utc=True); d["day"]=d.dt.dt.strftime("%Y-%m-%d")
d["f_bps"]=d.fundingRate*1e4
print(f"hours with both series: {len(d):,}  {d.dt.min():%Y-%m-%d} -> {d.dt.max():%Y-%m-%d}")
print(f"OI range {d.openInterest.min():,.0f} .. {d.openInterest.max():,.0f} HYPE (Bybit leg only)")

d["loi"]=np.log(d.openInterest)
d["doi_24h"]=d.loi.diff(24)*100          # % change, known at t
d["doi_168h"]=d.loi.diff(168)*100
d["f_past24"]=d.f_bps.rolling(24).mean() # funding is autocorrelated; control for it
rng=np.random.default_rng(3)
print(f"\n{'predictor':>12s} {'H':>5s} {'slope(bps fund per 1% OI)':>26s} {'t(day-clust)':>13s} {'R2':>7s} {'placebo t':>10s}")
for pred in ("doi_24h","doi_168h"):
    for Hh in (24,168,720):
        y=d.f_bps.shift(-Hh).rolling(Hh,min_periods=Hh//2).mean().shift(-0)  # mean funding over (t,t+H]
        y=d.f_bps[::-1].rolling(Hh,min_periods=Hh//2).mean()[::-1].shift(-1)
        m=d[pred].notna()&y.notna()&d.f_past24.notna()
        X=np.column_stack([np.ones(m.sum()), d[pred][m].values, d.f_past24[m].values])
        yy=y[m].values
        beta,*_=np.linalg.lstsq(X,yy,rcond=None)
        resid=yy-X@beta
        # day-clustered SE
        days=d.day[m].values; uq=pd.unique(days)
        XtX_inv=np.linalg.inv(X.T@X); meat=np.zeros((3,3))
        for g in uq:
            s=days==g; Xg=X[s]; ug=resid[s]
            meat+=np.outer(Xg.T@ug, Xg.T@ug)
        V=XtX_inv@meat@XtX_inv; se=np.sqrt(np.diag(V))[1]
        r2=1-resid.var()/yy.var()
        # placebo: shuffle the predictor across days
        pv=rng.permutation(d[pred][m].values)
        Xp=np.column_stack([np.ones(m.sum()), pv, d.f_past24[m].values])
        bp,*_=np.linalg.lstsq(Xp,yy,rcond=None); rp=yy-Xp@bp
        meatp=np.zeros((3,3)); XtXp=np.linalg.inv(Xp.T@Xp)
        for g in uq:
            s=days==g; ug=rp[s]; meatp+=np.outer(Xp[s].T@ug, Xp[s].T@ug)
        sep=np.sqrt(np.diag(XtXp@meatp@XtXp))[1]
        print(f"{pred:>12s} {Hh:4d}h {beta[1]:26.4f} {beta[1]/se:13.2f} {r2:7.3f} {bp[1]/sep:10.2f}")
print("""
READ: 'slope' = bps of hourly funding per +1% of OI, controlling for trailing funding.
Funding is highly autocorrelated, so the past-funding control does most of the work --
a small R2 increment from OI is what matters, not the total R2.""")

# ============================================================================
# CORRECTION. The table above is NOT trustworthy and I am not reporting it as a
# result. Two defects, both of which inflate t:
#   1. The forward window is 720 h but the SE clusters by DAY. Day clusters do
#      nothing about 30-day overlap -- consecutive rows share ~719/720 of their
#      target. The effective n is ~21 blocks, not 15,631 rows.
#   2. The placebo shuffles the predictor i.i.d., destroying its autocorrelation.
#      Against an autocorrelated target that placebo is far too easy to beat.
#      The right null is a CIRCULAR SHIFT, which preserves autocorrelation.
# Redone below with non-overlapping blocks and a circular-shift null.
# ============================================================================
print("\n"+"="*74); print("HONEST VERSION: non-overlapping blocks + circular-shift null"); print("="*74)
def fit(x,y):
    X=np.column_stack([np.ones(len(x)),x]); b,*_=np.linalg.lstsq(X,y,rcond=None); return b[1]
for pred,Hh in (("doi_168h",720),("doi_168h",168),("doi_24h",720)):
    y=d.f_bps[::-1].rolling(Hh,min_periods=Hh//2).mean()[::-1].shift(-1)
    m=(d[pred].notna()&y.notna()).values
    xs=d[pred].values[m]; ys=y.values[m]
    xb=xs[::Hh]; yb=ys[::Hh]                 # NON-OVERLAPPING blocks
    if len(xb)<5: print(f"  {pred} H={Hh}: only {len(xb)} blocks, skip"); continue
    b=fit(xb,yb)
    r=yb-(np.mean(yb)+b*(xb-np.mean(xb)))
    se=np.sqrt(np.sum(r**2)/(len(xb)-2)/np.sum((xb-np.mean(xb))**2))
    t=b/se
    # circular-shift null on the FULL series, then re-block (preserves autocorr)
    null=[]
    for k in range(1,400):
        sh=int(len(xs)*k/400)
        null.append(fit(np.roll(xs,sh)[::Hh], yb[:len(np.roll(xs,sh)[::Hh])]))
    null=np.array(null); p=(np.abs(null)>=abs(b)).mean()
    print(f"  {pred:>9s} H={Hh:4d}h  blocks n={len(xb):3d}  slope {b:+.4f}  t={t:+.2f}"
          f"   circular-shift null: |slope| >= ours in {p*100:.1f}% of 399 shifts")
    print(f"      -> {'NOT significant against a proper null' if p>0.05 else 'survives the circular-shift null'}"
          f"  (null slope sd {null.std():.4f} vs ours {abs(b):.4f})")
print("""
VERDICT: with the overlap handled and an autocorrelation-preserving null, the OI->funding
link is NOT established. Report it as an open question, not a finding. Economic size would
have mattered (~11 %/yr of APR per 50 % OI move) which is exactly why it needs the honest test
rather than the flattering one.""")
