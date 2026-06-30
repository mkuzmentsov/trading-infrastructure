"""Intraday MEAN-REVERSION probe at 5m / 1h (the right hypothesis for intraday).

#16b proved the TREND signal is dead intraday — but it also showed WHY: 57-61% of intraday bars are
range/chop, where trend whipsaws. Range is where mean-reversion *earns*. So this tests the opposite,
regime-appropriate signal: fade short-term dislocations.

Signal (a-priori, NO search — three fixed lookbacks reported side by side, not a best-pick):
  z = (close − SMA_n) / rolling_std_n ;  position = −tanh(z / scale)   (fade: short rich, long cheap)
Risk-scaled to constant per-bar vol (so Sharpe is regime-fair), lookahead-safe (signal shifted 1 bar).

The decisive split this exposes: GROSS Sharpe (does the signal predict at all?) vs NET after fees. If
gross > 0 but net < 0, there is real intraday MR alpha that taker fees eat — capturable only with maker/
limit fills. We report both taker (4.5bps) and maker (0bps) to locate exactly where any edge dies.

Usage:  PYTHONPATH=src python3 scripts/intraday_meanrev.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np

from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore

LOOKBACKS = [24, 48, 96]          # a-priori z-score windows (bars); reported all, not searched
SCALE = 1.5                        # tanh squash on the z-score
INTERVALS = ["5m", "1h"]
VENUE = "bvision"


def _sharpe(r, ppy):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 1 and r.std(ddof=1) > 0 else 0.0


def run_one(close, ret, n, ppy, fee_bps):
    import pandas as pd
    c = pd.Series(close)
    sma = c.rolling(n).mean()
    sd = c.rolling(n).std()
    z = (c - sma) / sd.replace(0.0, np.nan)
    sig = -np.tanh(z / SCALE)                                   # fade dislocations
    tvol = pd.Series(ret).rolling(n).std()                     # risk-scale to constant vol
    pos = (sig / tvol.replace(0.0, np.nan)).clip(-50, 50)      # bounded leverage
    pos = pos / pos.abs().rolling(500, min_periods=50).median().clip(lower=1e-9)  # normalize gross ~1
    w = pos.shift(1)                                            # lookahead-safe
    gross = w * ret
    turnover = (pos - pos.shift(1)).abs()
    cost = (turnover * fee_bps / 1e4).shift(1).fillna(0.0)
    net = (gross - cost).to_numpy()
    return _sharpe(gross.to_numpy(), ppy), _sharpe(net, ppy), float(turnover.mean())


def main() -> int:
    store = PointInTimeStore("./data")
    a = datetime(2019, 1, 1, tzinfo=timezone.utc); b = datetime(2027, 1, 1, tzinfo=timezone.utc)
    print("=== Intraday MEAN-REVERSION probe (BTC, bvision 2022-26) ===")
    print(f"signal = −tanh(z/{SCALE}); z over a-priori lookbacks {LOOKBACKS}; risk-scaled; lookahead-safe\n")
    hdr = f"{'interval':>8} {'lookback':>8} {'gross Sh':>9} {'net@maker':>10} {'net@taker':>10} {'turnover/bar':>13}"
    print(hdr); print("-" * len(hdr))
    for interval in INTERVALS:
        ppy = PERIODS_PER_YEAR[interval]
        df = store._frame([Symbol("BTC")], VENUE, interval, a, b).sort_values("ts").reset_index(drop=True)
        close = df["close"].astype(float).to_numpy()
        ret = np.concatenate([[0.0], np.diff(close) / close[:-1]])
        for n in LOOKBACKS:
            g, net_taker, to = run_one(close, ret, n, ppy, 4.5)
            _, net_maker, _ = run_one(close, ret, n, ppy, 0.0)
            print(f"{interval:>8} {n:>8} {g:>+9.2f} {net_maker:>+10.2f} {net_taker:>+10.2f} {to:>12.1%}")
        print()
    print("read: GROSS>0 ⇒ the MR signal predicts; if net@taker<0<gross, the alpha is real but eaten by")
    print("taker fees (only capturable with passive/maker fills, which carry adverse-selection + non-fill")
    print("risk this backtest does NOT model). net@taker>0 would be the only result that survives as-is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
