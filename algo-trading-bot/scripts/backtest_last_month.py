"""Backtest the last N days on Kraken Futures and report cumulative PnL.

The daily-trend strategy needs ~100 bars of feature warmup, so we replay the FULL
history through the real engine (warm features, faithful positions) and then slice the
equity/fills to the requested trailing window. Cumulative PnL is equity minus the
equity at the window open.

Emits a console summary and an interactive HTML (Plotly.js CDN, no install) with:
  - price candles + long/short holding bands for the window
  - a cumulative-PnL curve (USD) for the window
  - per-fill markers with realized PnL on hover

Usage:
    PYTHONPATH=src python3 scripts/backtest_last_month.py [--days 31] [--config configs/paper_kraken.toml] [--out last_month.html]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from algo_trading_bot.config import BotConfig
from algo_trading_bot.engine.backtest import Backtester


def load_config(path: str) -> BotConfig:
    import tomllib

    return BotConfig(**tomllib.loads(Path(path).read_text()))


HTML = """<!doctype html><html><head><meta charset="utf-8"/>
<title>__TITLE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>html,body{margin:0;background:#0f1115;color:#d6dae0;font:13px -apple-system,Segoe UI,Roboto,sans-serif}
#bar{padding:10px 16px;border-bottom:1px solid #222}#bar h1{font-size:15px;margin:0 0 4px}.meta{color:#8a93a0}
.pill{padding:1px 8px;border-radius:10px;margin-right:6px}.pos{background:#133b33;color:#42d6a4}.neg{background:#3b1717;color:#ff7a78}
#chart{width:100%;height:calc(100vh - 70px)}</style></head><body>
<div id="bar"><h1>__TITLE__</h1><div class="meta">__SUMMARY__ &nbsp;|&nbsp; drag to zoom · double-click to reset · hover for detail</div></div>
<div id="chart"></div>
<script>
const D=__DATA__;
const candle={type:'candlestick',name:'BTC/USD',x:D.t,open:D.o,high:D.h,low:D.l,close:D.c,
  increasing:{line:{color:'#26a69a'}},decreasing:{line:{color:'#ef5350'}},xaxis:'x',yaxis:'y'};
const longMk={type:'scatter',mode:'markers',name:'long fill',xaxis:'x',yaxis:'y',x:D.longEntries.x,y:D.longEntries.y,
  marker:{symbol:'triangle-up',size:10,color:'#26a69a',line:{color:'#0c1c18',width:1}},customdata:D.longEntries.cd,
  hovertemplate:'<b>LONG</b> %{x}<br>price %{y:,.0f}<br>qty %{customdata[0]:.4f}<br>realized %{customdata[1]:,.2f}<extra></extra>'};
const shortMk={type:'scatter',mode:'markers',name:'short fill',xaxis:'x',yaxis:'y',x:D.shortEntries.x,y:D.shortEntries.y,
  marker:{symbol:'triangle-down',size:10,color:'#ef5350',line:{color:'#1c0c0c',width:1}},customdata:D.shortEntries.cd,
  hovertemplate:'<b>SHORT</b> %{x}<br>price %{y:,.0f}<br>qty %{customdata[0]:.4f}<br>realized %{customdata[1]:,.2f}<extra></extra>'};
const pnl={type:'scatter',mode:'lines',name:'cumulative PnL',x:D.t,y:D.cum,fill:'tozeroy',
  line:{color:'#e6b800',width:1.6},fillcolor:'rgba(230,184,0,0.12)',xaxis:'x',yaxis:'y2',
  hovertemplate:'cum PnL $%{y:,.2f}<extra></extra>'};
const layout={paper_bgcolor:'#0f1115',plot_bgcolor:'#0f1115',font:{color:'#d6dae0'},
  margin:{l:64,r:24,t:8,b:30},showlegend:true,legend:{orientation:'h',x:0,y:1.08,bgcolor:'rgba(0,0,0,0)'},
  hovermode:'x unified',dragmode:'zoom',shapes:D.bands,
  xaxis:{domain:[0,1],anchor:'y2',type:'date',gridcolor:'#1c1f26',rangeslider:{visible:false}},
  yaxis:{domain:[0.34,1],title:'Price (USD)',gridcolor:'#1c1f26',side:'right'},
  yaxis2:{domain:[0,0.30],title:'Cum PnL ($)',gridcolor:'#1c1f26',side:'right',zeroline:true,zerolinecolor:'#3a3f4a'}};
Plotly.newPlot('chart',[candle,longMk,shortMk,pnl],layout,
  {responsive:true,scrollZoom:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d']});
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/paper_kraken.toml")
    ap.add_argument("--days", type=int, default=31)
    ap.add_argument("--out", default="replays/last_month.html")
    args = ap.parse_args()

    cfg = load_config(args.config)
    bt = Backtester(cfg)
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)

    bars = bt.load_bars(start, end, cfg.data_venue)
    result = bt.run(start, end, cfg.data_venue, bars=bars)

    ohlc = pd.DataFrame(
        [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close} for b in bars]
    ).set_index("ts")
    ohlc.index = pd.to_datetime(ohlc.index)
    eq = result.equity.reindex(ohlc.index, method="ffill").bfill()

    # trailing window measured from the last available bar
    last_ts = ohlc.index[-1]
    win_start = last_ts - pd.Timedelta(days=args.days)
    mask = ohlc.index >= win_start
    w_ohlc = ohlc[mask]
    w_eq = eq[mask]

    # cumulative PnL within the window (start of window = $0)
    eq0 = float(w_eq.iloc[0])
    cum = (w_eq - eq0)

    # net position per bar (LONG +qty / SHORT -qty, cumsum) -> bands
    trades = result.trades.copy()
    if not trades.empty:
        trades["ts"] = pd.to_datetime(trades["ts"])
    pos = pd.Series(0.0, index=ohlc.index)
    if not trades.empty:
        signed = trades.assign(signed_qty=np.where(trades["side"] == "LONG", trades["qty"], -trades["qty"]))
        cumpos = signed.groupby("ts")["signed_qty"].sum().cumsum()
        pos = cumpos.reindex(ohlc.index, method="ffill").fillna(0.0)
    direction = np.sign(pos[mask].round(8)).to_numpy()

    t = w_ohlc.index
    half = (t[1] - t[0]) / 2 if len(t) > 1 else pd.Timedelta(hours=12)
    bands, n_long, n_short, i = [], 0, 0, 0
    while i < len(direction):
        if direction[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < len(direction) and direction[j + 1] == direction[i]:
            j += 1
        is_long = direction[i] > 0
        bands.append({"type": "rect", "xref": "x", "yref": "y domain",
                      "x0": (t[i] - half).isoformat(), "x1": (t[j] + half).isoformat(),
                      "y0": 0, "y1": 1, "layer": "below", "line": {"width": 0},
                      "fillcolor": "rgba(38,166,154,0.13)" if is_long else "rgba(239,83,80,0.13)"})
        n_long += (j - i + 1) if is_long else 0
        n_short += (j - i + 1) if not is_long else 0
        i = j + 1
    n_flat = int((direction == 0).sum())

    # fills inside the window
    w_trades = trades[(trades["ts"] >= win_start)] if not trades.empty else trades
    long_x, long_y, long_cd, short_x, short_y, short_cd = [], [], [], [], [], []
    realized_win = 0.0
    wins = losses = 0
    for _, r in (w_trades.sort_values("ts").iterrows() if not w_trades.empty else []):
        ts_iso = pd.to_datetime(r["ts"]).isoformat()
        realized_win += float(r["realized"])
        if r["realized"] > 0:
            wins += 1
        elif r["realized"] < 0:
            losses += 1
        if r["side"] == "LONG":
            long_x.append(ts_iso); long_y.append(r["price"]); long_cd.append([r["qty"], r["realized"]])
        else:
            short_x.append(ts_iso); short_y.append(r["price"]); short_cd.append([r["qty"], r["realized"]])

    end_pnl = float(cum.iloc[-1])
    pnl_pct = end_pnl / eq0
    peak = float(cum.cummax().iloc[-1])
    trough = float(cum.min())
    n_trades = 0 if w_trades is None or w_trades.empty else len(w_trades)

    data = {
        "t": [x.isoformat() for x in t],
        "o": w_ohlc["open"].tolist(), "h": w_ohlc["high"].tolist(),
        "l": w_ohlc["low"].tolist(), "c": w_ohlc["close"].tolist(),
        "cum": [round(v, 2) for v in cum.tolist()],
        "bands": bands,
        "longEntries": {"x": long_x, "y": long_y, "cd": long_cd},
        "shortEntries": {"x": short_x, "y": short_y, "cd": short_cd},
    }
    title = (f"Kraken Futures BTC/USD 1d — last {args.days}d backtest  "
             f"({t[0]:%Y-%m-%d} → {t[-1]:%Y-%m-%d})")
    summary = (f"<b>cumulative PnL ${end_pnl:,.2f} ({pnl_pct:+.2%})</b> · "
               f"{n_trades} fills (W {wins}/L {losses}) · "
               f"bars LONG {n_long} / SHORT {n_short} / FLAT {n_flat} · "
               f"peak +${peak:,.0f} / trough ${trough:,.0f}")
    html = (HTML.replace("__TITLE__", title).replace("__SUMMARY__", summary)
            .replace("__DATA__", json.dumps(data)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html)

    print(f"=== Last {args.days}d backtest ({t[0]:%Y-%m-%d} -> {t[-1]:%Y-%m-%d}) ===")
    print(f"window-open equity: ${eq0:,.2f}   close equity: ${float(w_eq.iloc[-1]):,.2f}")
    print(f"CUMULATIVE PnL:     ${end_pnl:,.2f}  ({pnl_pct:+.2%})")
    print(f"peak +${peak:,.2f}  /  trough ${trough:,.2f}")
    print(f"fills: {n_trades}  (winning {wins} / losing {losses})  realized in window ${realized_win:,.2f}")
    print(f"bars held: LONG {n_long} / SHORT {n_short} / FLAT {n_flat}")
    print(f"interactive chart -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
