"""Cross-sectional alt long-short on a basket of Binance daily klines.

Each day: rank coins by a signal, LONG the top quartile / SHORT the bottom quartile,
dollar-neutral, hold one day, net of turnover cost. Being market-neutral removes the
unpredictable market beta that sank the single-asset directional models — the bet is
only on *relative* performance (which is far more predictable than absolute direction).

Honest: time-split train/test, realistic turnover cost, equity-curve viz.
CAVEAT: fixed current basket = SURVIVORSHIP BIAS (only coins that survived are
included). Real point-in-time results would be lower. Treat as an upper bound.

Run: python3 pattern-bot/xsectional.py
"""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
COINS = ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
         "LTC", "BCH", "TRX", "ATOM", "ETC", "XLM", "NEAR", "FIL", "UNI", "AAVE", "ALGO", "EOS"]
FEE = 5 / 1e4          # per side, per unit of turnover (≈ taker; Kraken credit ≈ 0)
TOPK_FRAC = 0.25       # long top quartile / short bottom quartile
MIN_NAMES = 8          # need at least this many coins with data that day


def load_panel() -> pd.DataFrame:
    cols = {}
    for p in sorted(DATA.glob("*USDT_1d.parquet")):      # auto-discover the whole basket
        c = p.name.replace("USDT_1d.parquet", "")
        d = pd.read_parquet(p).sort_values("time")
        idx = pd.to_datetime(d["time"], unit="ms", utc=True).dt.floor("D")
        cols[c] = pd.Series(d["close"].values, index=idx)
    return pd.DataFrame(cols).sort_index()


def make_signals(px: pd.DataFrame):
    return {
        "mom7":  px / px.shift(7) - 1,
        "mom14": px / px.shift(14) - 1,
        "mom30": px / px.shift(30) - 1,
        "rev1":  -(px / px.shift(1) - 1),    # short-term reversal: long losers
        "rev3":  -(px / px.shift(3) - 1),
        "rev7":  -(px / px.shift(7) - 1),
    }


def _leg(names, vol_row, weight):
    """Weights within one leg (sum=1): equal, or inverse-vol (risk-parity-ish)."""
    if weight == "volinv" and vol_row is not None:
        iv = 1.0 / vol_row[names].replace(0, np.nan)
        iv = iv.fillna(iv.mean()) if iv.notna().any() else pd.Series(1.0, index=names)
        return iv / iv.sum()
    return pd.Series(1.0 / len(names), index=names)


def backtest(sig: pd.DataFrame, nxt: pd.DataFrame, dates, vol=None, weight="equal", fee=FEE):
    prev = pd.Series(0.0, index=sig.columns)
    eq, xs, ys, daily, turns = 1.0, [], [], [], []
    for dt in dates:
        s, r = sig.loc[dt], nxt.loc[dt]
        valid = s.notna() & r.notna()
        if valid.sum() < MIN_NAMES:
            continue
        sv = s[valid].sort_values()
        k = max(1, int(len(sv) * TOPK_FRAC))
        longs, shorts = sv.index[-k:], sv.index[:k]
        vr = vol.loc[dt] if vol is not None else None
        w = pd.Series(0.0, index=sig.columns)
        w[longs] = 0.5 * _leg(longs, vr, weight)
        w[shorts] = -0.5 * _leg(shorts, vr, weight)
        turn = (w - prev).abs().sum()
        net = (w * r.fillna(0)).sum() - turn * fee
        eq *= (1 + net); prev = w
        xs.append(dt); ys.append(eq); daily.append(net); turns.append(turn)
    d = np.array(daily)
    if len(d) < 5:
        return None, xs, ys, daily
    sharpe = d.mean() / d.std() * np.sqrt(365) if d.std() > 0 else 0.0
    yrs = max((xs[-1] - xs[0]).days / 365.25, 1e-9)
    cur = np.array(ys); peak = np.maximum.accumulate(cur)
    return dict(n=len(d), sharpe=sharpe, cagr=(cur[-1] ** (1 / yrs) - 1),
                ret=cur[-1] - 1, dd=float(np.max((peak - cur) / peak)),
                turn=float(np.mean(turns)), hit=float((d > 0).mean())), xs, ys, daily


def main():
    px = load_panel()
    print(f"basket: {px.shape[1]} coins, {len(px)} days, "
          f"{px.index[0].date()} → {px.index[-1].date()}  (FEE {FEE*1e4:.0f}bps/side, top/bottom {TOPK_FRAC:.0%}, INVERSE-VOL weighted)")
    print("CAVEAT: fixed current basket = survivorship bias; treat as an upper bound.\n")
    nxt = px.pct_change().shift(-1)
    vol = px.pct_change().rolling(20).std()    # 20d realized vol for inverse-vol weighting
    sigs = make_signals(px)
    split = pd.Timestamp("2023-07-01", tz="UTC")
    W = "volinv"

    print(f"{'signal':<8}{'window':<7}{'n':>5}{'sharpe':>8}{'CAGR%':>8}{'ret%':>9}{'maxDD%':>8}{'turn':>6}{'hit%':>6}")
    fig = go.Figure()
    for name, sg in sigs.items():
        sgl = sg.shift(1)                      # signal known at PRIOR close (no lookahead)
        for tag, mask in (("train", px.index < split), ("TEST", px.index >= split)):
            r, *_ = backtest(sgl, nxt, px.index[mask], vol=vol, weight=W)
            if r:
                print(f"{name:<8}{tag:<7}{r['n']:>5}{r['sharpe']:>8.2f}{r['cagr']*100:>7.1f}"
                      f"{r['ret']*100:>8.1f}{r['dd']*100:>7.1f}{r['turn']:>6.2f}{r['hit']*100:>5.0f}")
        r, xs, ys, _ = backtest(sgl, nxt, px.index, vol=vol, weight=W)
        if ys:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=name))

    # --- focus on the OOS winner: cost sensitivity + per-year consistency (TEST) ---
    best = "mom14"; sgl = sigs[best].shift(1)
    print(f"\n[{best}] TEST cost sensitivity (Sharpe / CAGR%):")
    for f in (0.0, 2.5/1e4, 5/1e4, 10/1e4):
        r, *_ = backtest(sgl, nxt, px.index[px.index >= split], vol=vol, weight=W, fee=f)
        print(f"   {f*1e4:>4.1f} bps/side  →  Sharpe {r['sharpe']:>5.2f}   CAGR {r['cagr']*100:>+6.1f}%")
    print(f"\n[{best}] per-year (full period, {FEE*1e4:.0f}bps):")
    _, xs, _, daily = backtest(sgl, nxt, px.index, vol=vol, weight=W)
    dd = pd.Series(daily, index=pd.to_datetime(xs))
    for yr, g in dd.groupby(dd.index.year):
        s = g.mean() / g.std() * np.sqrt(365) if g.std() > 0 else 0
        print(f"   {yr}: ret {((1+g).prod()-1)*100:>+7.1f}%   Sharpe {s:>5.2f}   ({len(g)}d)")

    fig.add_vline(x=split, line_dash="dot", line_color="#888", annotation_text="train | test")
    fig.add_hline(y=1.0, line_color="#555")
    fig.update_layout(title=f"Cross-sectional alt L/S — equity ({px.shape[1]} coins, {FEE*1e4:.0f}bps/side, inverse-vol, daily)",
                      template="plotly_dark", height=620, hovermode="x unified", yaxis_type="log")
    out = ROOT / "charts" / "xsectional_equity.html"
    fig.write_html(str(out), include_plotlyjs="cdn")
    print(f"\n[chart] -> {out}")


if __name__ == "__main__":
    main()
