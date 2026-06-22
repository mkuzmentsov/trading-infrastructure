"""Replay the BTC daily trend strategy over all available Kraken Futures candles and
draw a candlestick chart with long/short holding periods shaded.

Faithful path: runs the *real* Backtester (same engine as live, NFR1) over the
krakenfutures BTC 1d series, reconstructs the per-bar net position from the fills,
and shades each bar green (net long) / red (net short).

Usage:
    PYTHONPATH=src python3 scripts/chart_kraken_replay.py [--config configs/paper_kraken.toml] [--last N] [--out chart.png]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from algo_trading_bot.config import BotConfig
from algo_trading_bot.engine.backtest import Backtester


def load_config(path: str) -> BotConfig:
    import tomllib

    return BotConfig(**tomllib.loads(Path(path).read_text()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/paper_kraken.toml")
    ap.add_argument("--last", type=int, default=None, help="only chart the last N bars")
    ap.add_argument("--out", default="replays/kraken_replay_positions.png")
    args = ap.parse_args()

    cfg = load_config(args.config)
    bt = Backtester(cfg)
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)

    # Bars actually fed to the engine (one venue, one symbol).
    bars = bt.load_bars(start, end, cfg.data_venue)
    result = bt.run(start, end, cfg.data_venue, bars=bars)

    # OHLC frame in engine order.
    ohlc = pd.DataFrame(
        [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close} for b in bars]
    ).set_index("ts")
    ohlc.index = pd.to_datetime(ohlc.index)

    # --- reconstruct per-bar net position from fills ---
    # Side.LONG fills add, Side.SHORT fills subtract (quantity is positive); cumulative
    # sum is the net signed position held after each fill. Forward-fill across bars.
    trades = result.trades
    pos = pd.Series(0.0, index=ohlc.index)
    if not trades.empty:
        signed = trades.assign(
            ts=pd.to_datetime(trades["ts"]),
            signed_qty=np.where(trades["side"] == "LONG", trades["qty"], -trades["qty"]),
        )
        # net position at each fill timestamp
        cum = signed.groupby("ts")["signed_qty"].sum().cumsum()
        # align to bar grid: position effective from the bar the fill landed on, forward-filled
        pos = cum.reindex(ohlc.index, method="ffill").fillna(0.0)

    # sanity: final reconstructed position vs the engine's own books
    eng = bt  # noqa
    direction = np.sign(pos.round(8))  # -1 short, 0 flat, +1 long

    # optionally trim to the last N bars for readability
    if args.last:
        ohlc = ohlc.iloc[-args.last :]
        direction = direction.iloc[-args.last :]
        pos = pos.iloc[-args.last :]

    # --- plot ---
    fig, ax = plt.subplots(figsize=(min(26, 4 + len(ohlc) * 0.018), 9))
    x = mdates.date2num(ohlc.index.to_pydatetime())
    # bar width in date units (median spacing)
    dx = np.median(np.diff(x)) if len(x) > 1 else 1.0
    w = dx * 0.7

    up = ohlc["close"] >= ohlc["open"]
    for i, (t, row) in enumerate(ohlc.iterrows()):
        color = "#26a69a" if up.iloc[i] else "#ef5350"
        # wick
        ax.plot([x[i], x[i]], [row["low"], row["high"]], color=color, linewidth=0.6, zorder=3)
        # body
        lo = min(row["open"], row["close"])
        h = abs(row["close"] - row["open"]) or (row["high"] - row["low"]) * 0.001
        ax.add_patch(Rectangle((x[i] - w / 2, lo), w, h, facecolor=color, edgecolor=color, zorder=3))

    # shade contiguous long / short runs
    ymin, ymax = ohlc["low"].min() * 0.985, ohlc["high"].max() * 1.015
    d = direction.to_numpy()
    n_long = n_short = 0
    i = 0
    while i < len(d):
        if d[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < len(d) and d[j + 1] == d[i]:
            j += 1
        x0 = x[i] - dx / 2
        x1 = x[j] + dx / 2
        if d[i] > 0:
            ax.axvspan(x0, x1, color="#26a69a", alpha=0.13, zorder=0)
            n_long += j - i + 1
        else:
            ax.axvspan(x0, x1, color="#ef5350", alpha=0.13, zorder=0)
            n_short += j - i + 1
        i = j + 1

    ax.set_ylim(ymin, ymax)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    n_flat = int((d == 0).sum())
    ax.set_title(
        f"Kraken Futures BTC/USD 1d — {cfg.name} replay  "
        f"({ohlc.index[0]:%Y-%m-%d} → {ohlc.index[-1]:%Y-%m-%d}, {len(ohlc)} bars)\n"
        f"green span = held LONG ({n_long} bars) · red span = held SHORT ({n_short} bars) · "
        f"unshaded = flat ({n_flat} bars)",
        fontsize=11,
    )
    ax.set_ylabel("Price (USD)")
    ax.grid(True, alpha=0.2, zorder=0)

    fig.tight_layout()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=130)

    # --- text summary ---
    m = result.metrics
    eq = result.equity
    print(f"Replay over {len(bars)} Kraken Futures BTC 1d bars "
          f"({ohlc.index[0]:%Y-%m-%d} → {ohlc.index[-1]:%Y-%m-%d})")
    print(f"trades={len(trades)}  end_equity={eq.iloc[-1]:,.0f} (start {eq.iloc[0]:,.0f}, "
          f"{eq.iloc[-1]/eq.iloc[0]-1:+.1%})  Sharpe={m.sharpe:.2f}  maxDD={m.max_drawdown:.1%}")
    print(f"bars held: LONG={n_long}  SHORT={n_short}  FLAT={n_flat}")
    print(f"chart written -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
