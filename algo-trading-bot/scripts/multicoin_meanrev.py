"""5m mean-reversion across multiple coins — does the BTC fee-death generalize, and does a basket help?

BTC's 5m MR died because its spread is ~0 (nothing for a maker to earn, #24c). Less-liquid alts have
wider spreads + often stronger reversion, so the economics may differ. Test the SAME a-priori signal
(threshold MR, lb48, enter |z|>2, exit |z|<0.5) on each coin — gross Sharpe (signal quality) and net at
maker 2bp — plus an equal-weight PORTFOLIO (diversification: independent MR signals → smoother equity).

NOTE on the net column: PaperBroker-style fills earn ZERO spread (pessimistic for wide-spread alts — a
real maker would earn part of the spread my model ignores). So net@2bp is a LOWER bound for alts; if it's
already near breakeven, the maker case is promising. Lookahead-safe.

Usage:  PYTHONPATH=src python3 scripts/multicoin_meanrev.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from algo_trading_bot.core.types import Symbol
from algo_trading_bot.data.bars import PERIODS_PER_YEAR
from algo_trading_bot.data.store import PointInTimeStore

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
LB, ENTRY, EXIT, MAKER_BPS = 48, 2.0, 0.5, 2.0


def _sharpe(r, ppy):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ppy)) if r.size > 2 and r.std(ddof=1) > 0 else 0.0


def threshold_pos(close):
    c = pd.Series(close)
    z = ((c - c.rolling(LB).mean()) / c.rolling(LB).std().replace(0.0, np.nan)).fillna(0.0).to_numpy()
    pos = np.zeros(len(z)); cur = 0.0
    for t in range(len(z)):
        if cur == 0.0:
            cur = -1.0 if z[t] > ENTRY else (1.0 if z[t] < -ENTRY else 0.0)
        elif abs(z[t]) < EXIT:
            cur = 0.0
        pos[t] = cur
    return pos


def coin_returns(close, ppy):
    ret = np.concatenate([[0.0], np.diff(close) / close[:-1]])
    pos = threshold_pos(close)
    w = np.concatenate([[0.0], pos[:-1]])
    gross = w * ret
    turn = np.abs(np.concatenate([[0.0], np.diff(pos)]))
    net = gross - np.concatenate([[0.0], turn[:-1] * MAKER_BPS / 1e4])
    return gross, net, float(turn.sum() / (len(pos) / ppy))


def main() -> int:
    store = PointInTimeStore("./data")
    a = datetime(2019, 1, 1, tzinfo=timezone.utc); b = datetime(2027, 1, 1, tzinfo=timezone.utc)
    ppy = PERIODS_PER_YEAR["5m"]
    print(f"=== 5m threshold MR across coins (bvision 2022-26, a-priori lb{LB} |z|>{ENTRY}/<{EXIT}, maker {MAKER_BPS}bp) ===\n")
    hdr = f"{'coin':>6} {'GROSS Sh':>9} {'NET Sh':>8} {'net ret':>9} {'trades/yr':>10}"
    print(hdr); print("-" * len(hdr))
    nets = {}
    for c in COINS:
        df = store._frame([Symbol(c)], "bvision", "5m", a, b).sort_values("ts").reset_index(drop=True)
        if df.empty:
            print(f"{c:>6}  (no data)"); continue
        close = df["close"].astype(float).to_numpy()
        gross, net, tpy = coin_returns(close, ppy)
        nets[c] = net
        eq = np.cumprod(1 + net)
        print(f"{c:>6} {_sharpe(gross, ppy):>+9.2f} {_sharpe(net, ppy):>+8.2f} {eq[-1]-1:>+8.1%} {tpy:>9,.0f}")

    # equal-weight portfolio of the per-coin NET streams (diversification)
    L = min(len(v) for v in nets.values())
    port = np.mean(np.vstack([v[-L:] for v in nets.values()]), axis=0)
    print(f"\n{'PORTFOLIO':>6} (equal-weight {len(nets)} coins, net):  Sharpe {_sharpe(port, ppy):+.2f}  "
          f"ret {np.cumprod(1+port)[-1]-1:+.1%}")
    # average pairwise correlation of the gross signals (how independent are the edges?)
    grosses = {}
    for c in nets:
        df = store._frame([Symbol(c)], "bvision", "5m", a, b).sort_values("ts").reset_index(drop=True)
        grosses[c] = coin_returns(df["close"].astype(float).to_numpy(), ppy)[0][-L:]
    M = np.corrcoef(np.vstack([grosses[c] for c in nets]))
    avg_corr = (M.sum() - len(nets)) / (len(nets) * (len(nets) - 1))
    print(f"avg pairwise gross-signal correlation: {avg_corr:.2f}  (low ⇒ real √N diversification benefit)")
    print("\nread: GROSS>0 = signal predicts on that coin; NET = after maker fee (LOWER bound — earns NO spread,")
    print("pessimistic for wide-spread alts). If alts have stronger gross AND the portfolio net Sharpe clears 0,")
    print("the wider-spread maker economics are worth a real spread study. If net is still <0 everywhere, the")
    print("fee-death generalizes and diversification just smooths a bleed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
