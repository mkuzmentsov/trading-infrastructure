"""ML signal research — train a model on BTC, validate held-out + CROSS-COIN.

Target: triple-barrier outcome — from each bar, does price hit +b before -b within
H bars (b = vol-scaled, so it's comparable across coins). The model predicts
P(long wins). Features are SCALE-INVARIANT (returns, ratios, z-scores) so a
BTC-trained model transfers to ETH/XRP/etc. on any venue.

Honest by construction:
  - BTC split by TIME: train (→2022-07) / val (→2024-01, picks the threshold) / test (rest)
  - ETH/XRP/SOL: whole series is OUT-OF-SAMPLE (never-seen symbols)
  - no shuffling, costs included, one position at a time

Run: python3 pattern-bot/ml_research.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

H = 24              # horizon bars (1 day on 1h)
ATR_N = 14
BARRIER_K = 1.5     # TP/SL = BARRIER_K × ATR%  (vol-scaled → cross-coin comparable)
FEE_BPS = 9.5       # per side (taker + slippage); round-trip = 2×
START_EQ = 1000.0
POS_FRAC = 0.50     # 25% margin × 2x = 50% notional exposure
COST = 2 * FEE_BPS / 1e4


def feats(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["vol"]
    x = pd.DataFrame(index=df.index)
    lr = np.log(c / c.shift(1))
    for n in (1, 2, 3, 6, 12, 24, 48, 72, 168):
        x[f"ret{n}"] = np.log(c / c.shift(n))
    for n in (12, 24, 72):
        x[f"vol{n}"] = lr.rolling(n).std()
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_N).mean()
    x["atr_pct"] = atr / c
    d = c.diff(); up = d.clip(lower=0).rolling(14).mean(); dn = (-d.clip(upper=0)).rolling(14).mean()
    x["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    for n in (12, 24, 72, 200):
        x[f"sma{n}"] = c / c.rolling(n).mean() - 1
    m, s = c.rolling(20).mean(), c.rolling(20).std()
    x["bb"] = (c - m) / (2 * s)
    e12, e26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    macd = e12 - e26
    x["macd_h"] = (macd - macd.ewm(span=9).mean()) / c
    x["vol_z"] = (v - v.rolling(24).mean()) / v.rolling(24).std()
    rng = (h - l).replace(0, np.nan)
    x["body"] = (c - o) / rng
    x["uwick"] = (h - pd.concat([o, c], axis=1).max(axis=1)) / rng
    x["lwick"] = (pd.concat([o, c], axis=1).min(axis=1) - l) / rng
    return x.replace([np.inf, -np.inf], np.nan)


def extras(sym, df):
    """Non-price features: funding rate + perp/index basis (asof-merged onto bars).
    All scale-invariant (rates), so they transfer across coins."""
    ex = pd.DataFrame(index=df.index)
    fp, pp = DATA / f"{sym}_funding.parquet", DATA / f"{sym}_premium_1h.parquet"
    if fp.exists():
        f = pd.read_parquet(fp).sort_values("time")
        fr = pd.merge_asof(df[["time"]], f, on="time", direction="backward")["funding_rate"]
        ex["funding_now"] = fr.values
        ex["funding_z"] = ((fr - fr.rolling(720).mean()) / fr.rolling(720).std()).values
        ex["funding_chg"] = (fr - fr.shift(24)).values
    if pp.exists():
        p = pd.read_parquet(pp).sort_values("time")
        pm = pd.merge_asof(df[["time"]], p, on="time", direction="backward")["premium"]
        ex["basis_now"] = pm.values
        ex["basis_z"] = ((pm - pm.rolling(720).mean()) / pm.rolling(720).std()).values
        ex["basis_chg"] = (pm - pm.shift(24)).values
    op = DATA / f"{sym}_ofi_1h.parquet"
    if op.exists():
        o = pd.read_parquet(op).sort_values("time")
        om = pd.merge_asof(df[["time"]], o, on="time", direction="backward")
        ofi = om["ofi"]; nt = om["ntrades"]; asz = om["avg_size"]
        ex["ofi"] = ofi.values
        ex["ofi_ma6"] = ofi.rolling(6).mean().values
        ex["ofi_ma24"] = ofi.rolling(24).mean().values
        ex["ofi_z"] = ((ofi - ofi.rolling(720).mean()) / ofi.rolling(720).std()).values
        ex["buy_frac"] = om["buy_frac"].values
        ex["ntrades_z"] = ((nt - nt.rolling(720).mean()) / nt.rolling(720).std()).values
        ex["avgsize_z"] = ((asz - asz.rolling(720).mean()) / asz.rolling(720).std()).values
        ex["whale"] = (om["max_size"] / asz).values
    return ex.replace([np.inf, -np.inf], np.nan)


def barrier_labels(df: pd.DataFrame, atr_pct: pd.Series):
    """Returns (y, er, exit_bar): y=1 if a long wins (upper barrier first / positive
    time-exit), er = realized fractional return of a LONG, exit_bar = index it closed."""
    c, hi, lo = df["close"].values, df["high"].values, df["low"].values
    b = (BARRIER_K * atr_pct.values)
    n = len(c)
    y = np.full(n, np.nan); er = np.full(n, np.nan); xb = np.full(n, -1)
    for t in range(n - 1):
        bt = b[t]
        if not np.isfinite(bt) or bt <= 0:
            continue
        up, dnp = c[t] * (1 + bt), c[t] * (1 - bt)
        end = min(t + H, n - 1)
        r, eb, hit = None, end, 0
        for j in range(t + 1, end + 1):
            if hi[j] >= up:
                r, eb, hit = bt, j, 1; break
            if lo[j] <= dnp:
                r, eb, hit = -bt, j, -1; break
        if hit == 0:
            r, eb = (c[end] / c[t] - 1), end
        er[t] = r; xb[t] = eb; y[t] = 1.0 if r > 0 else 0.0
    return y, er, xb


def backtest(times, p, er, xb, up_thr, dn_thr):
    eq = START_EQ; i = 0; n = len(p); xs, ys, rets = [], [], []
    while i < n - 1:
        if not (np.isfinite(p[i]) and np.isfinite(er[i])):
            i += 1; continue
        if p[i] > up_thr:
            ret = er[i] - COST
        elif p[i] < dn_thr:
            ret = -er[i] - COST
        else:
            i += 1; continue
        eq += eq * POS_FRAC * ret
        rets.append(ret * POS_FRAC); xs.append(times[i]); ys.append(eq)
        i = int(xb[i]) + 1 if xb[i] > i else i + 1
    return np.array(rets), xs, ys, eq


def stats(rets, ys):
    if len(rets) == 0:
        return dict(n=0, win=0, pf=0, ret=0, dd=0)
    w = rets[rets > 0].sum(); l = abs(rets[rets < 0].sum())
    cur = np.array(ys); peak = np.maximum.accumulate(cur); dd = float(np.max((peak - cur) / peak))
    return dict(n=len(rets), win=float((rets > 0).mean()), pf=(w / l if l else float("inf")),
                ret=ys[-1] / START_EQ - 1, dd=dd)


def prep(sym):
    df = pd.read_parquet(DATA / f"{sym}_1h.parquet").sort_values("time").reset_index(drop=True)
    X = feats(df)
    X = pd.concat([X, extras(sym, df)], axis=1)     # + funding/basis features
    y, er, xb = barrier_labels(df, X["atr_pct"])
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df, X, y, er, xb


def main():
    ms = lambda d: int(pd.Timestamp(d, tz="UTC").value // 10**6)
    # Order-flow (aggTrades) data starts 2024-01, so the OFI-feature run lives in
    # the 2024–2026 window: train 18mo / val 6mo / test ~5mo.
    DS = ms("2024-01-01")
    TR_END, VAL_END = ms("2025-07-01"), ms("2026-01-01")

    print("loading + feature/label engineering (BTC, price + funding/basis)...")
    btc, Xb, yb, erb, xbb = prep("BTCUSDT")
    t = btc["time"].values
    tr = (t >= DS) & (t < TR_END) & np.isfinite(yb)
    va = (t >= TR_END) & (t < VAL_END) & np.isfinite(yb)
    te = (t >= VAL_END) & np.isfinite(yb)
    feat_cols = list(Xb.columns)

    # Heavily regularized: shallow trees, large leaves, strong L2 — to close the
    # train/val gap and give any *real* (small) signal a fair chance to show.
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03,
                                         max_leaf_nodes=8, min_samples_leaf=500,
                                         l2_regularization=10.0, max_features=0.6,
                                         early_stopping=True, validation_fraction=0.15,
                                         random_state=0)
    clf.fit(Xb[tr].values, yb[tr].astype(int))
    print(f"trained on {tr.sum()} BTC bars, {len(feat_cols)} features\n")

    def auc(mask):
        return roc_auc_score(yb[mask].astype(int), clf.predict_proba(Xb[mask].values)[:, 1])
    print(f"AUC  train {auc(tr):.3f}  val {auc(va):.3f}  test {auc(te):.3f}   (0.5 = no skill)\n")

    # pick symmetric threshold margin on VALIDATION by best costed return
    pv = clf.predict_proba(Xb[va].values)[:, 1]
    best_m, best_ret = 0.05, -9e9
    for mgn in (0.02, 0.04, 0.06, 0.08, 0.10, 0.12):
        r, _, ys, _ = backtest(btc["time"].values[va], pv, erb[va], xbb[va], 0.5 + mgn, 0.5 - mgn)
        s = stats(r, ys)
        if s["n"] >= 20 and s["ret"] > best_ret:
            best_ret, best_m = s["ret"], mgn
    up_thr, dn_thr = 0.5 + best_m, 0.5 - best_m
    print(f"threshold margin chosen on val: ±{best_m:.2f}  (long>{up_thr:.2f}, short<{dn_thr:.2f})\n")

    print(f"{'set':<18}{'n':>5}{'win':>6}{'PF':>6}{'ret%':>8}{'dd%':>7}")
    import plotly.graph_objects as go
    fig = go.Figure()

    def evaluate(label, times, X, er, xb, plot=True):
        p = clf.predict_proba(X.values)[:, 1]
        r, xs, ys, _ = backtest(times, p, er, xb, up_thr, dn_thr)
        s = stats(r, ys)
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        print(f"{label:<18}{s['n']:>5}{s['win']*100:>5.0f}%{pf:>6}{s['ret']*100:>+7.1f}{s['dd']*100:>6.1f}")
        if plot and xs:
            fig.add_trace(go.Scatter(x=pd.to_datetime(xs, unit="ms", utc=True), y=ys, mode="lines", name=label))

    # BTC, by period
    evaluate("BTC train", btc["time"].values[tr], Xb[tr], erb[tr], xbb[tr], plot=False)
    evaluate("BTC val", btc["time"].values[va], Xb[va], erb[va], xbb[va], plot=False)
    evaluate("BTC test", btc["time"].values[te], Xb[te], erb[te], xbb[te])
    # (BTC-only this run — cross-coin validation will be done independently later,
    #  once BTC shows whether funding/basis adds real signal.)

    fig.add_hline(y=START_EQ, line_color="#555")
    fig.update_layout(title=f"ML signal equity ($1k, 25%×2x, costs) — BTC-trained model · "
                            f"margin ±{best_m:.2f} · barrier {BARRIER_K}×ATR / {H}h",
                      template="plotly_dark", height=620, hovermode="x unified")
    out = ROOT / "charts" / "ml_equity.html"
    fig.write_html(str(out), include_plotlyjs="cdn")
    print(f"\n[chart] -> {out}")


if __name__ == "__main__":
    main()
