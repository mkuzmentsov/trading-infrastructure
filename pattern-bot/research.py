"""Strategy research on the long Binance OOS data, done HONESTLY:
  - split BTCUSDT 1h into TRAIN (2018–2022) and TEST (2023–2026)
  - grid-search the rectangle params on TRAIN only
  - apply the TRAIN-best config UNTOUCHED to TEST  → that test number is the real edge
  - also run the current combined config + per-pattern, train vs test
  - write an equity-curve comparison chart

The whole point: anything that only looks good in-sample is overfitting. The TEST
column (data never used to choose params) is what decides if a strategy is real.

Usage: python3 pattern-bot/research.py
"""
from __future__ import annotations
import sys, importlib.util, itertools
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bot"))
_spec = importlib.util.spec_from_file_location("bt", str(ROOT / "backtest.py"))
bt = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bt)
from strategy import resolve_detectors  # noqa: E402

DATA = ROOT / "data" / "BTCUSDT_1h.parquet"
START_EQ = 1000.0


def ms(date: str) -> int:
    return int(pd.Timestamp(date, tz="UTC").value // 10**6)


TRAIN = (ms("2018-01-01"), ms("2023-01-01"))
TEST = (ms("2023-01-01"), ms("2026-07-01"))

df = pd.read_parquet(DATA).sort_values("time").reset_index(drop=True)
ALL = df[["time", "open", "high", "low", "close", "vol"]].to_dict("records")
base_cfg, RT = bt._load_cfg_dict(str(ROOT / "bot" / "config.example.yaml"))


def candles(window):
    a, b = window
    return [c for c in ALL if a <= c["time"] < b]


def run(pattern_types, overrides, window):
    cfg = dict(base_cfg)
    cfg["pattern"] = {**base_cfg.get("pattern", {}), "pattern_types": pattern_types}
    cfg["pattern_overrides"] = overrides
    dets = resolve_detectors(cfg)
    return bt.backtest_coin(candles(window), "BTCUSDT", dets, RT, START_EQ)


def stats(r):
    T = r["trades"]
    if not T:
        return dict(n=0, win=0.0, avgR=0.0, totR=0.0, pf=0.0, ret=0.0, dd=r.get("max_dd", 0.0))
    R = np.array([t["R"] for t in T]); pnl = np.array([t["pnl"] for t in T])
    w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
    return dict(n=len(T), win=float((R > 0).mean()), avgR=float(R.mean()),
                totR=float(R.sum()), pf=(w / l if l else float("inf")),
                ret=r["total_ret"], dd=r["max_dd"])


def line(tag, s):
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    print(f"{tag:<34}{s['n']:>5}{s['win']*100:>6.0f}%{s['avgR']:>7.2f}{s['totR']:>8.1f}"
          f"{pf:>6}{s['ret']*100:>9.1f}{s['dd']*100:>7.1f}")


REC = base_cfg["pattern_overrides"]["rectangle"]
DBL = base_cfg["pattern_overrides"]["double"]
WDG = base_cfg["pattern_overrides"]["wedge"]

print(f"BTCUSDT 1h  TRAIN 2018–2022 / TEST 2023–2026  (sizing 25%×2x, ${START_EQ:.0f} start, costs in)\n")
print(f"{'strategy':<34}{'n':>5}{'win':>6}{'avgR':>7}{'totR':>8}{'PF':>6}{'ret%':>9}{'dd%':>7}")

# --- baselines (current config), train vs test ---
combined = {"rectangle": REC, "double": DBL, "wedge": WDG}
for label, pts, ov in [("combined (rect+dbl+wdg)", ["rectangle", "double", "wedge"], combined),
                       ("rectangle (current)", ["rectangle"], {"rectangle": REC}),
                       ("double (current)", ["double"], {"double": DBL}),
                       ("wedge (current)", ["wedge"], {"wedge": WDG})]:
    line(label + " [train]", stats(run(pts, ov, TRAIN)))
    line(label + " [TEST]", stats(run(pts, ov, TEST)))

# --- grid-search rectangle on TRAIN, then lock and apply to TEST ---
grid = {"tri_window": [40, 60], "tri_flat_slope": [0.0008, 0.0015],
        "min_trough_depth_pct": [0.015, 0.02, 0.03], "stop_height_frac": [0.0, 0.5]}
best, best_tr = None, -1e9
for combo in (dict(zip(grid, v)) for v in itertools.product(*grid.values())):
    ov = {"rectangle": {**REC, **combo}}
    s = stats(run(["rectangle"], ov, TRAIN))
    if s["n"] >= 20 and s["totR"] > best_tr:
        best_tr, best = s["totR"], combo
print(f"\n[grid] best rectangle on TRAIN: {best}  (train totR {best_tr:+.1f})")
best_ov = {"rectangle": {**REC, **best}}
line("rectangle TUNED-on-train [train]", stats(run(["rectangle"], best_ov, TRAIN)))
test_best = run(["rectangle"], best_ov, TEST)
line("rectangle TUNED-on-train [TEST]", stats(test_best))

# --- equity-curve chart on the FULL period for the headline candidates ---
import plotly.graph_objects as go
fig = go.Figure()


def add_curve(name, pts, ov):
    r = run(pts, ov, (ms("2018-01-01"), ms("2026-07-01")))
    eq = START_EQ; xs, ys = [], []
    for t in sorted(r["trades"], key=lambda x: x["exit_dt"]):
        eq += t["pnl"]; xs.append(pd.to_datetime(t["exit_dt"])); ys.append(eq)
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=name))


add_curve("combined", ["rectangle", "double", "wedge"], combined)
add_curve("rectangle (current)", ["rectangle"], {"rectangle": REC})
add_curve("rectangle (train-tuned)", ["rectangle"], best_ov)
add_curve("double", ["double"], {"double": DBL})
fig.add_vline(x=pd.to_datetime("2023-01-01"), line_dash="dot", line_color="#888",
              annotation_text="train | test")
fig.add_hline(y=START_EQ, line_color="#555")
fig.update_layout(title="BTCUSDT 1h — equity ($1k start, 25%×2x) — left of line = in-sample",
                  template="plotly_dark", height=620, hovermode="x unified")
out = ROOT / "charts" / "research_equity.html"
out.parent.mkdir(exist_ok=True)
fig.write_html(str(out), include_plotlyjs="cdn")
print(f"\n[chart] equity curves -> {out}")
