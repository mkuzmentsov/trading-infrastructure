"""Experiment #20 — a high-leverage strategy INSIDE the ring-fenced degen sleeve, with REAL liquidation.

Question: does levering a genuine edge (the daily trend signal) hard beat a coin-flip at the same
leverage — once you model that the position can be LIQUIDATED before the trend pays? Liquidation is the
thing the Binance-leaderboard accounts ignore until it ends them.

Mechanics (faithful to Binance USDT-M isolated margin):
  * data: `umperp__BTC__1d` (perp price, for entry/PnL) + `ummark__BTC__1d` (MARK price — what actually
    triggers liquidation). 2020–2026, 6.4y.
  * the degen sleeve rebalances daily to leverage L in the signal's direction. Position notional = L·equity.
  * intrabar liquidation: a long is liquidated if the day's MARK adverse excursion (1 − mark_low/mark_open)
    ≥ the liq buffer (1/L − maintenance_margin); symmetric for shorts (mark_high/mark_open − 1). On
    liquidation the isolated sleeve goes to 0 and HALTS (guarantee #2/#3 of #19).
  * if not liquidated: equity ·= (1 + L·signal·ret_close − fees·turnover). Daily rebalancing at high L
    pays heavy fees (signal flips cost ~2L turnover) — also modeled.

Strategies compared at each L ∈ {2,3,5,10,20}:
  * TREND  — sign of an EMA(20/100) crossover on the perp (a real, if thin, edge levered hard).
  * NAIVE  — always long (the leaderboard's "10–20× and pray" directional bet).

Output is the FULL outcome distribution from block-bootstrapped 1-year sleeve paths (it's a lottery):
P(liquidated), median / 5th / 95th-pct terminal multiple, mean. The mean hides the ruin; the
distribution shows it.

Usage:  PYTHONPATH=src python3 scripts/degen_liquidation.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.store import PointInTimeStore

LEVERAGES = [2, 3, 5, 10, 20]
MAINT_MARGIN = 0.005          # 0.5% maintenance margin (BTC USDT-M, moderate notional)
FEE_BPS = 4.5
EMA_FAST, EMA_SLOW = 20, 100
N_BOOT = 20000
BLOCK = 21                    # ~1 trading month blocks preserve trend/vol autocorr
HORIZON = 365                 # 1-year sleeve paths


def load():
    store = PointInTimeStore("./data")
    a = datetime(2019, 1, 1, tzinfo=timezone.utc); b = datetime(2027, 1, 1, tzinfo=timezone.utc)
    perp = store._frame([Symbol("BTC")], "umperp", "1d", a, b).sort_values("ts").reset_index(drop=True)
    mark = store._frame([Symbol("BTC")], "ummark", "1d", a, b).sort_values("ts").reset_index(drop=True)
    df = perp.merge(mark[["ts", "open", "high", "low", "close"]], on="ts", suffixes=("", "_m"))
    return df


def build_bars(df: pd.DataFrame) -> dict:
    close = df["close"].astype(float)
    ret = close.pct_change().fillna(0.0).to_numpy()
    ema_f = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()
    sig = np.sign((ema_f - ema_s).to_numpy())                       # +1 long / -1 short / 0 flat
    sig = np.where(sig == 0, 1.0, sig)
    # MARK intrabar adverse excursions (the liquidation trigger)
    mo, mh, ml = df["open_m"].astype(float).to_numpy(), df["high_m"].astype(float).to_numpy(), df["low_m"].astype(float).to_numpy()
    adv_long = np.clip(1.0 - ml / mo, 0.0, None)                    # worst intrabar drop (hurts longs)
    adv_short = np.clip(mh / mo - 1.0, 0.0, None)                   # worst intrabar rise (hurts shorts)
    return {"ret": ret[1:], "sig_trend": sig[1:], "adv_long": adv_long[1:], "adv_short": adv_short[1:]}


def simulate(idx, lev, mode, bars):
    """Replay a sequence of bar-indices through the sleeve at leverage `lev`. Returns terminal multiple
    (0.0 if liquidated). `mode`='trend' uses the signal; 'naive' is always long."""
    liq_buf = 1.0 / lev - MAINT_MARGIN
    fee = FEE_BPS / 1e4
    eq = 1.0
    prev_pos = 0.0
    ret, sig_t, adv_l, adv_s = bars["ret"], bars["sig_trend"], bars["adv_long"], bars["adv_short"]
    for i in idx:
        s = sig_t[i] if mode == "trend" else 1.0
        pos = lev * s
        # liquidation check on MARK adverse excursion in the position's direction
        adverse = adv_l[i] if s > 0 else adv_s[i]
        if adverse >= liq_buf:
            return 0.0                                             # wiped — isolated sleeve to zero
        turnover = abs(pos - prev_pos)
        eq *= (1.0 + pos * ret[i] - fee * turnover)
        if eq <= 0.0:
            return 0.0
        prev_pos = pos
    return eq


def main() -> int:
    df = load()
    bars = build_bars(df)
    n = len(bars["ret"])
    print(f"=== Degen sleeve: high-leverage trend vs naive, with mark-price liquidation ===")
    print(f"BTC USDT-M perp, {df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()}  ({n} bars)")
    print(f"maint margin {MAINT_MARGIN:.1%}  fee {FEE_BPS}bps  EMA {EMA_FAST}/{EMA_SLOW}  "
          f"{N_BOOT} bootstrapped {HORIZON}d sleeve paths\n")

    rng = np.random.default_rng(0)
    n_blocks = int(np.ceil(HORIZON / BLOCK))
    starts_pool = rng.integers(0, n - BLOCK, size=(N_BOOT, n_blocks))
    paths = [np.concatenate([np.arange(s, s + BLOCK) for s in starts_pool[k]])[:HORIZON] for k in range(N_BOOT)]

    hdr = (f"{'mode':>6} {'lev':>4} {'P(liq)':>7} {'P(>1x)':>7} {'median':>8} {'5th':>7} "
           f"{'95th':>9} {'mean':>9}")
    for mode in ("trend", "naive"):
        print(hdr); print("-" * len(hdr))
        for lev in LEVERAGES:
            term = np.array([simulate(p, lev, mode, bars) for p in paths])
            liq = float((term == 0.0).mean())
            survive_gain = float((term > 1.0).mean())
            med = float(np.median(term)); p5 = float(np.percentile(term, 5))
            p95 = float(np.percentile(term, 95)); mean = float(term.mean())
            print(f"{mode:>6} {lev:>3}× {liq:>7.1%} {survive_gain:>7.1%} {med:>8.2f}x {p5:>6.2f}x "
                  f"{p95:>8.2f}x {mean:>8.2f}x")
        print()

    print("read: 'P(liq)'=share of 1-yr sleeve paths fully liquidated. 'median'=typical terminal multiple of")
    print("the sleeve (1.00x = breakeven, 0 = wiped). 'mean' is dragged up by rare moonshots (95th) — it is")
    print("NOT what you typically get. Compare trend vs naive at each leverage: does the real edge survive")
    print("liquidation better, and at what leverage does liquidation make signal quality irrelevant?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
