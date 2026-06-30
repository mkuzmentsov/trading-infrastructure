"""5m mean-reversion under PASSIVE (maker) execution — does the gross edge survive real fills?

#24 found a real 5m MR signal (gross Sharpe +0.74) that taker fees annihilate. The only way to capture
it is to POST passively (maker) instead of crossing the spread. This models that honestly, including the
two things that make passive execution NOT free:

  1. MAKER FEE instead of taker (1-2 bps vs 4.5) — the cheap part.
  2. CONDITIONAL FILLS (the expensive part): a resting limit only fills when price trades TO it. We post
     a limit at the signal bar's close and fill (next bar) only if that bar's range reaches it — buy fills
     if low ≤ limit, sell if high ≥ limit. Unfilled orders are cancelled (no chase). This is where ADVERSE
     SELECTION enters: you preferentially fill the buys where price kept dropping and miss the ones that
     ran away — exactly the fills you least want.

We report, on the same signal: GROSS (close-fill, no cost — the upper bound) vs TAKER (cross, 4.5bps) vs
MAKER@{1,2}bps with conditional fills, plus the realized fill rate. Lookahead-safe; fills use only the
bar AFTER the signal.

Caveat this still cannot model with 5m bars: intrabar queue position (did you actually get filled, or did
the tape trade through without filling your size?) and partial fills. So MAKER here is still an OPTIMISTIC
bound — full fill on touch. If it's negative even here, refining won't save it.

Usage:  PYTHONPATH=src python3 scripts/intraday_maker.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore

LOOKBACKS = [24, 48, 96]
SCALE = 1.5


def _sharpe(r, ppy):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def signal(close, ret, n):
    c = pd.Series(close)
    z = (c - c.rolling(n).mean()) / c.rolling(n).std().replace(0.0, np.nan)
    sig = -np.tanh(z / SCALE)
    tvol = pd.Series(ret).rolling(n).std()
    pos = (sig / tvol.replace(0.0, np.nan)).clip(-50, 50)
    pos = pos / pos.abs().rolling(500, min_periods=50).median().clip(lower=1e-9)
    return pos.fillna(0.0).to_numpy()


def sim_taker(pos, ret, close, ppy, fee_bps):
    w = np.concatenate([[0.0], pos[:-1]])                       # lookahead-safe
    turn = np.abs(np.concatenate([[0.0], np.diff(pos)]))
    cost = np.concatenate([[0.0], (turn[:-1] * fee_bps / 1e4)])
    return _sharpe(w * ret - cost, ppy), 1.0


def sim_maker(pos_target, ret, o, h, l, c, ppy, fee_bps):
    """Passive: each bar post a limit at the prior bar's close toward the target; fill only if THIS bar's
    range reaches it. Returns (Sharpe, fill_rate). Position only moves on fills (conditional → adverse)."""
    n = len(c)
    held = np.zeros(n)
    pnl = np.zeros(n)
    fills = 0
    orders = 0
    pos = 0.0
    for t in range(1, n):
        limit = c[t - 1]                                        # post at last close (decided at t-1)
        want = pos_target[t - 1]
        delta = want - pos
        if abs(delta) > 1e-9:
            orders += 1
            buy = delta > 0
            touched = (l[t] <= limit) if buy else (h[t] >= limit)
            if touched:                                          # full fill at the limit price
                fills += 1
                pnl[t] -= abs(delta) * (fee_bps / 1e4)          # maker fee on traded fraction
                # filled at `limit`==c[t-1]; the new position earns this bar from limit to close
                pnl[t] += pos * (c[t] / c[t - 1] - 1.0)         # old position over the full bar
                pnl[t] += delta * (c[t] / limit - 1.0)          # new piece from fill price to close
                pos = want
            else:
                pnl[t] += pos * (c[t] / c[t - 1] - 1.0)         # unfilled: carry old position
        else:
            pnl[t] += pos * (c[t] / c[t - 1] - 1.0)
        held[t] = pos
    return _sharpe(pnl, ppy), (fills / orders if orders else 0.0)


def threshold_signal(close, n, entry_z, exit_z):
    """Low-turnover MR: enter full-size fade only when |z|>entry_z, hold until |z|<exit_z, then flat.
    Far fewer trades than the continuous tanh signal — the realistic way to trade a costly edge."""
    c = pd.Series(close)
    z = ((c - c.rolling(n).mean()) / c.rolling(n).std().replace(0.0, np.nan)).fillna(0.0).to_numpy()
    pos = np.zeros(len(z)); cur = 0.0
    for t in range(len(z)):
        if cur == 0.0:
            if z[t] > entry_z: cur = -1.0
            elif z[t] < -entry_z: cur = 1.0
        elif abs(z[t]) < exit_z:
            cur = 0.0
        pos[t] = cur
    return pos


def main() -> int:
    store = PointInTimeStore("./data")
    a = datetime(2019, 1, 1, tzinfo=timezone.utc); b = datetime(2027, 1, 1, tzinfo=timezone.utc)
    df = store._frame([Symbol("BTC")], "bvision", "5m", a, b).sort_values("ts").reset_index(drop=True)
    o, h, l, c = (df[x].astype(float).to_numpy() for x in ("open", "high", "low", "close"))
    ret = np.concatenate([[0.0], np.diff(c) / c[:-1]])
    ppy = PERIODS_PER_YEAR["5m"]

    print("=== 5m mean-reversion under passive (maker) execution ===")
    print(f"BTC 5m bvision, {df['ts'].iloc[0].date()} → {df['ts'].iloc[-1].date()} ({len(df)} bars)\n")
    hdr = (f"{'lookback':>8} {'GROSS':>7} {'taker4.5':>9} {'maker1bp':>9} {'maker2bp':>9} {'fill rate':>10}")
    print(hdr); print("-" * len(hdr))
    for n in LOOKBACKS:
        pos = signal(c, ret, n)
        g, _ = sim_taker(pos, ret, c, ppy, 0.0)
        tk, _ = sim_taker(pos, ret, c, ppy, 4.5)
        m1, fr = sim_maker(pos, ret, o, h, l, c, ppy, 1.0)
        m2, _ = sim_maker(pos, ret, o, h, l, c, ppy, 2.0)
        print(f"{n:>8} {g:>+7.2f} {tk:>+9.2f} {m1:>+9.2f} {m2:>+9.2f} {fr:>9.1%}")

    # Steelman: LOW-TURNOVER threshold version (enter on |z|>2, exit on |z|<0.5)
    print("\n--- low-turnover threshold MR (enter |z|>2.0, exit |z|<0.5) ---")
    print(f"{'lookback':>8} {'GROSS':>7} {'taker4.5':>9} {'maker1bp':>9} {'maker2bp':>9} {'trades/yr':>10}")
    for n in LOOKBACKS:
        pos = threshold_signal(c, n, 2.0, 0.5)
        g, _ = sim_taker(pos, ret, c, ppy, 0.0)
        tk, _ = sim_taker(pos, ret, c, ppy, 4.5)
        m1, _ = sim_maker(pos, ret, o, h, l, c, ppy, 1.0)
        m2, _ = sim_maker(pos, ret, o, h, l, c, ppy, 2.0)
        trades_yr = int(np.abs(np.diff(pos)).sum() / 2 / (len(c) / ppy))
        print(f"{n:>8} {g:>+7.2f} {tk:>+9.2f} {m1:>+9.2f} {m2:>+9.2f} {trades_yr:>10,}")

    print("\nread: MAKER columns are an OPTIMISTIC bound (full fill on touch, no queue/partial-fill risk,")
    print("no spread EARNED — so pessimistic on spread capture, optimistic on fills). If even the low-turnover")
    print("version is ≤0 at maker, the 5m edge is not capturable retail. Daily book NET Sharpe ≈0.8-1.2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
