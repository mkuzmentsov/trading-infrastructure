"""Per-pattern parameter tuning (IN-SAMPLE — use only as a hypothesis generator).

For each pattern family, sweep a small grid of its relevant parameters on the
given coin/interval, run the backtest for each combo, and print a leaderboard.

Ranked by TOTAL R among combos with >= --min-trades (so a 2-trade fluke with a
huge avg R can't win). This optimizes ON the data it's scored on, so the "best"
configs are upper bounds — they MUST be re-checked out-of-sample before trust.

Usage:
    python3 pattern-bot/tune.py [--coins BTC] [--interval 1h] [--family rectangle]
        [--min-trades 5] [--config bot/config.yaml]
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))
import importlib.util
_spec = importlib.util.spec_from_file_location("bt", str(Path(__file__).resolve().parent / "backtest.py"))
bt = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bt)

DATA_DIR = Path(__file__).resolve().parent / "data"

# Per-family parameter grids (pattern-side). Risk-side stop_height_frac is swept for all.
PIVOT_GRID = {
    "peak_tolerance_pct": [0.008, 0.012, 0.02],
    "min_trough_depth_pct": [0.02, 0.03, 0.05],
    "max_break_bars": [12, 24],
    "vol_confirm_mult": [0.0, 1.5],
}
TREND_GRID = {
    "tri_window": [40, 60],
    "tri_flat_slope": [0.0005, 0.0008, 0.0015],
    "min_trough_depth_pct": [0.01, 0.02],
    "vol_confirm_mult": [0.0, 1.5],
}
FLAG_GRID = {
    "flag_pole_bars": [6, 10],
    "flag_max_bars": [12, 20],
    "flag_pole_min_pct": [0.03, 0.05],
    "flag_max_retrace": [0.4, 0.6],
    "vol_confirm_mult": [0.0, 1.5],
}
PATTERN_GRIDS = {
    "double": PIVOT_GRID, "head_shoulders": PIVOT_GRID, "triple": PIVOT_GRID,
    "triangle": TREND_GRID, "wedge": TREND_GRID, "rectangle": TREND_GRID,
    "flag": FLAG_GRID,
}
RISK_GRID = {"stop_height_frac": [0.0, 0.5]}


def _combos(grid: dict):
    keys = list(grid)
    for vals in itertools.product(*[grid[k] for k in keys]):
        yield dict(zip(keys, vals))


def tune_family(family: str, candles: list[dict], coin: str, pcfg0, rcfg0, rt: float,
                min_trades: int):
    rows = []
    for pov in _combos(PATTERN_GRIDS[family]):
        pcfg = dataclasses.replace(pcfg0, pattern_types=(family,), **pov)
        for rov in _combos(RISK_GRID):
            rcfg = dataclasses.replace(rcfg0, **rov)
            r = bt.backtest_coin(candles, coin, [(family, pcfg, rcfg)], rt)
            tr = r["trades"]
            if not tr:
                continue
            R = [t["R"] for t in tr]
            wins = [x for x in R if x > 0]
            rows.append({
                "n": len(tr), "win": len(wins) / len(tr), "avgR": sum(R) / len(R),
                "totR": sum(R), "pf": r["profit_factor"],
                **pov, **rov,
            })
    if not rows:
        print(f"  {family}: no trades in any combo")
        return None
    df = pd.DataFrame(rows)
    elig = df[df["n"] >= min_trades]
    note = ""
    if elig.empty:                       # nothing met the bar — relax, but flag it
        elig = df[df["n"] >= 2]
        note = f"  (none reached {min_trades} trades; showing n>=2 — treat as noise)"
    elig = elig.sort_values("totR", ascending=False)
    pkeys = list(PATTERN_GRIDS[family]) + list(RISK_GRID)
    print(f"\n=== {family} ({len(rows)} combos){note} ===")
    print(f"{'n':>3}{'win%':>6}{'avgR':>6}{'PF':>6}{'totR':>7}   params")
    for _, r in elig.head(6).iterrows():
        ps = " ".join(f"{k}={r[k]:g}" for k in pkeys)
        pf = "inf" if r["pf"] == float("inf") else f"{r['pf']:.2f}"
        print(f"{int(r['n']):>3}{r['win']*100:>5.0f}%{r['avgR']:>6.2f}{pf:>6}{r['totR']:>+7.1f}   {ps}")
    return elig.iloc[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--config", default="pattern-bot/bot/config.example.yaml")
    ap.add_argument("--family", default=None, help="tune only this family (default: all)")
    ap.add_argument("--min-trades", type=int, default=5)
    args = ap.parse_args()

    pcfg0, rcfg0, rt = bt._load_cfg(args.config)
    families = [args.family] if args.family else list(PATTERN_GRIDS)
    for coin in [c.strip().upper() for c in args.coins.split(",") if c.strip()]:
        f = DATA_DIR / f"{coin}_{args.interval}.parquet"
        if not f.exists():
            print(f"{coin}: no data"); continue
        df = pd.read_parquet(f).sort_values("time").reset_index(drop=True)
        cols = ["time", "open", "high", "low", "close"] + (["vol"] if "vol" in df.columns else [])
        candles = df[cols].to_dict("records")
        print(f"\n########## {coin} {args.interval} — {len(candles)} bars  "
              f"(ranked by total R, min {args.min_trades} trades) ##########")
        for fam in families:
            tune_family(fam, candles, coin, pcfg0, rcfg0, rt, args.min_trades)


if __name__ == "__main__":
    main()
