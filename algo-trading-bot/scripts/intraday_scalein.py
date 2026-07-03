"""Does DISCIPLINED scale-in (tranche averaging-down) beat fixed-size 5m mean-reversion?

The runner takes ONE fixed-size position. The question: if price keeps dislocating, should we add tranches
(bigger when cheaper), expecting a stronger reversion? This backtests it honestly on the full 4.4y 5m data,
gross and net at maker fees, so we know BEFORE changing the live runner.

Variants (fade the z-score; exit ALL tranches when |z|<exit):
  fixed      — 1 tranche at |z|>2                       (the current runner)
  scale-2    — add a 2nd tranche at |z|>3   (cap 2 units)
  scale-3    — add 2nd/3rd at |z|>3 / |z|>4  (cap 3 units)
Tranches RATCHET (never reduced until full exit) — disciplined, NOT unlimited martingale.

The tension: scale-in is bigger exactly in the deepest dislocations — which revert hardest IF they revert,
but are also where a dislocation can be a regime break (continuation), and it pays more fees (more tranches).
Net effect is the empirical question. Lookahead-safe (z at t acts at t+1). Compares Sharpe (risk-adjusted,
the fair metric) + cum return + maxDD + avg exposure.

Usage:  PYTHONPATH=src python3 scripts/intraday_scalein.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore

LOOKBACK = 48
EXIT_Z = 0.5
MAKER_BPS = 2.0


def _sharpe(r, ppy):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 2 and r.std(ddof=1) > 0 else 0.0


def scalein_positions(z: np.ndarray, entry_levels: list[float], exit_z: float) -> np.ndarray:
    """Signed integer tranche count over time. Fade: z>0 (rich)->short, z<0 (cheap)->long.
    Tranches ratchet up as |z| crosses successive levels; all closed when |z|<exit."""
    pos = 0.0
    out = np.zeros(len(z))
    for t in range(len(z)):
        az = abs(z[t])
        sgn = -1.0 if z[t] > 0 else 1.0
        want_n = sum(az > lvl for lvl in entry_levels)               # tranches justified by depth
        if pos == 0.0:
            pos = sgn * want_n
        elif az < exit_z:
            pos = 0.0
        else:
            cur_sign = 1.0 if pos > 0 else -1.0
            if sgn == cur_sign:                                       # same side: ratchet up only
                pos = cur_sign * max(abs(pos), want_n)
            # opposite side while still beyond exit: hold (don't flip mid-trade)
        out[t] = pos
    return out


def run(close, ret, levels, ppy):
    c = pd.Series(close)
    z = ((c - c.rolling(LOOKBACK).mean()) / c.rolling(LOOKBACK).std().replace(0.0, np.nan)).fillna(0.0).to_numpy()
    pos = scalein_positions(z, levels, EXIT_Z)
    w = np.concatenate([[0.0], pos[:-1]])                            # lookahead-safe
    gross = w * ret
    turn = np.abs(np.concatenate([[0.0], np.diff(pos)]))
    cost = np.concatenate([[0.0], turn[:-1] * MAKER_BPS / 1e4])
    net = gross - cost
    eq = np.cumprod(1.0 + net)
    maxdd = float((eq / np.maximum.accumulate(eq) - 1.0).min())
    entries = int(((pos != 0) & (np.concatenate([[0.0], pos[:-1]]) == 0)).sum())
    return {"gross_sh": _sharpe(gross, ppy), "net_sh": _sharpe(net, ppy),
            "net_ret": float(eq[-1] - 1.0), "maxdd": maxdd,
            "avg_exposure": float(np.abs(pos).mean()), "entries": entries,
            "turnover_yr": float(turn.sum() / (len(pos) / ppy))}


def main() -> int:
    store = PointInTimeStore("./data")
    a = datetime(2019, 1, 1, tzinfo=timezone.utc); b = datetime(2027, 1, 1, tzinfo=timezone.utc)
    df = store._frame([Symbol("BTC")], "bvision", "5m", a, b).sort_values("ts").reset_index(drop=True)
    close = df["close"].astype(float).to_numpy()
    ret = np.concatenate([[0.0], np.diff(close) / close[:-1]])
    ppy = PERIODS_PER_YEAR["5m"]

    print(f"=== 5m MR: fixed vs disciplined scale-in (BTC bvision, {df['ts'].iloc[0].date()}→{df['ts'].iloc[-1].date()}, "
          f"{len(df):,} bars) ===")
    print(f"lookback {LOOKBACK}  exit|z|<{EXIT_Z}  maker {MAKER_BPS}bp\n")
    variants = {"fixed  (|z|>2)": [2.0], "scale-2 (>2,3)": [2.0, 3.0], "scale-3 (>2,3,4)": [2.0, 3.0, 4.0]}
    hdr = f"{'variant':>17} {'GROSS Sh':>9} {'NET Sh':>8} {'net ret':>9} {'maxDD':>8} {'avg|pos|':>9} {'turn/yr':>8}"
    print(hdr); print("-" * len(hdr))
    res = {}
    for name, lv in variants.items():
        r = run(close, ret, lv, ppy); res[name] = r
        print(f"{name:>17} {r['gross_sh']:>+9.2f} {r['net_sh']:>+8.2f} {r['net_ret']:>+8.1%} "
              f"{r['maxdd']:>8.1%} {r['avg_exposure']:>8.2f}x {r['turnover_yr']:>7.0f}")
    print("\nread: scale-in WINS only if NET Sharpe rises vs fixed WITHOUT a worse maxDD — i.e. the extra")
    print("size in deep dislocations is well-timed AND survives the added fees. If NET Sharpe falls or maxDD")
    print("blows out, averaging down is the leaderboard's trap (#20/#21), not an edge. (All gross<net-irrelevant;")
    print("the daily trend book is the capturable edge — this only tweaks an already fee-bound 5m signal.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
