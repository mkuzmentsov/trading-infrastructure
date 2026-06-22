"""Replay the BTC daily-trend strategy over all available Kraken Futures candles and
emit a self-contained INTERACTIVE HTML chart (Plotly.js from CDN — no install).

Faithful path: runs the real Backtester (same engine as live, NFR1), reconstructs the
per-bar net position from the fills, and renders:
  - candlesticks (zoom / pan / hover OHLC)
  - shaded long (green) / short (red) holding bands
  - trade markers (▲ long / ▼ short) with hover: side, qty, price, realized PnL
  - an equity sub-chart sharing the x-axis
  - range buttons (1m / 3m / 6m / 1y / all) + crosshair

Usage:
    PYTHONPATH=src python3 scripts/chart_kraken_interactive.py \
        [--config configs/paper_kraken.toml] [--out kraken_replay.html]
Then open the HTML in any browser.
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


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  html,body{margin:0;background:#0f1115;color:#d6dae0;font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif}
  #bar{padding:10px 16px;border-bottom:1px solid #222}
  #bar h1{font-size:15px;margin:0 0 4px}
  #bar .meta{color:#8a93a0}
  .pill{display:inline-block;padding:1px 8px;border-radius:10px;margin-right:6px}
  .long{background:#133b33;color:#42d6a4}.short{background:#3b1717;color:#ff7a78}.flat{background:#2a2d33;color:#aab}
  #chart{width:100%;height:calc(100vh - 70px)}
</style>
</head>
<body>
<div id="bar">
  <h1>__TITLE__</h1>
  <div class="meta">
    __SUMMARY__ &nbsp;|&nbsp;
    <span class="pill long">LONG __NLONG__ bars</span>
    <span class="pill short">SHORT __NSHORT__ bars</span>
    <span class="pill flat">FLAT __NFLAT__ bars</span>
    &nbsp; drag to zoom · double-click to reset · hover for detail
  </div>
</div>
<div id="chart"></div>
<script>
const D = __DATA__;

const candle = {
  type:'candlestick', name:'BTC/USD', x:D.t,
  open:D.o, high:D.h, low:D.l, close:D.c,
  increasing:{line:{color:'#26a69a'}}, decreasing:{line:{color:'#ef5350'}},
  xaxis:'x', yaxis:'y'
};

const longMk = {
  type:'scatter', mode:'markers', name:'long entry', xaxis:'x', yaxis:'y',
  x:D.longEntries.x, y:D.longEntries.y,
  marker:{symbol:'triangle-up', size:11, color:'#26a69a', line:{color:'#0c1c18',width:1}},
  customdata:D.longEntries.cd,
  hovertemplate:'<b>LONG entry</b><br>%{x}<br>price %{y:,.0f}<br>qty %{customdata[0]:.4f}<br>net pos %{customdata[1]:.4f}<extra></extra>'
};
const shortMk = {
  type:'scatter', mode:'markers', name:'short entry', xaxis:'x', yaxis:'y',
  x:D.shortEntries.x, y:D.shortEntries.y,
  marker:{symbol:'triangle-down', size:11, color:'#ef5350', line:{color:'#1c0c0c',width:1}},
  customdata:D.shortEntries.cd,
  hovertemplate:'<b>SHORT entry</b><br>%{x}<br>price %{y:,.0f}<br>qty %{customdata[0]:.4f}<br>net pos %{customdata[1]:.4f}<extra></extra>'
};

const equity = {
  type:'scatter', mode:'lines', name:'equity', x:D.t, y:D.eq,
  line:{color:'#e6b800', width:1.4}, xaxis:'x', yaxis:'y2',
  hovertemplate:'equity %{y:,.0f}<extra></extra>'
};
const posLine = {
  type:'scatter', mode:'lines', name:'net position', x:D.t, y:D.pos,
  line:{color:'#7aa2ff', width:1, shape:'hv'}, xaxis:'x', yaxis:'y3',
  hovertemplate:'net pos %{y:.4f}<extra></extra>'
};

const layout = {
  paper_bgcolor:'#0f1115', plot_bgcolor:'#0f1115', font:{color:'#d6dae0'},
  margin:{l:64,r:24,t:10,b:30}, showlegend:true,
  legend:{orientation:'h', x:0, y:1.06, bgcolor:'rgba(0,0,0,0)'},
  hovermode:'x unified', dragmode:'zoom',
  shapes:D.bands,
  xaxis:{
    domain:[0,1], anchor:'y3', type:'date', gridcolor:'#1c1f26',
    rangeslider:{visible:false},
    rangeselector:{ bgcolor:'#1c1f26', activecolor:'#33405e', font:{color:'#d6dae0'},
      buttons:[
        {count:1,label:'1m',step:'month',stepmode:'backward'},
        {count:3,label:'3m',step:'month',stepmode:'backward'},
        {count:6,label:'6m',step:'month',stepmode:'backward'},
        {count:1,label:'1y',step:'year',stepmode:'backward'},
        {step:'all',label:'all'} ] }
  },
  yaxis:{ domain:[0.42,1], title:'Price (USD)', gridcolor:'#1c1f26', side:'right', autorange:true, fixedrange:false },
  yaxis2:{ domain:[0.18,0.40], title:'Equity', gridcolor:'#1c1f26', side:'right' },
  yaxis3:{ domain:[0,0.16], title:'Position', gridcolor:'#1c1f26', side:'right', zeroline:true, zerolinecolor:'#3a3f4a' }
};

Plotly.newPlot('chart', [candle, longMk, shortMk, equity, posLine], layout,
  {responsive:true, scrollZoom:true, displaylogo:false,
   modeBarButtonsToRemove:['lasso2d','select2d']});
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/paper_kraken.toml")
    ap.add_argument("--out", default="replays/kraken_replay.html")
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

    # --- reconstruct per-bar net position from fills (LONG +qty / SHORT -qty, cumsum) ---
    trades = result.trades
    pos = pd.Series(0.0, index=ohlc.index)
    if not trades.empty:
        signed = trades.assign(
            ts=pd.to_datetime(trades["ts"]),
            signed_qty=np.where(trades["side"] == "LONG", trades["qty"], -trades["qty"]),
        )
        cum = signed.groupby("ts")["signed_qty"].sum().cumsum()
        pos = cum.reindex(ohlc.index, method="ffill").fillna(0.0)
    direction = np.sign(pos.round(8)).to_numpy()

    # contiguous long/short bands -> plotly shapes (full-height on price subplot)
    t = ohlc.index
    bands = []
    n_long = n_short = 0
    i = 0
    while i < len(direction):
        if direction[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < len(direction) and direction[j + 1] == direction[i]:
            j += 1
        half = (t[1] - t[0]) / 2 if len(t) > 1 else pd.Timedelta(hours=12)
        x0 = (t[i] - half).isoformat()
        x1 = (t[j] + half).isoformat()
        is_long = direction[i] > 0
        bands.append({
            "type": "rect", "xref": "x", "yref": "y domain",
            "x0": x0, "x1": x1, "y0": 0, "y1": 1, "layer": "below", "line": {"width": 0},
            "fillcolor": "rgba(38,166,154,0.13)" if is_long else "rgba(239,83,80,0.13)",
        })
        if is_long:
            n_long += j - i + 1
        else:
            n_short += j - i + 1
        i = j + 1
    n_flat = int((direction == 0).sum())

    # entry markers: a fill that flips/opens direction. Mark every fill at its price.
    long_x, long_y, long_cd = [], [], []
    short_x, short_y, short_cd = [], [], []
    if not trades.empty:
        running = 0.0
        for _, r in trades.sort_values("ts").iterrows():
            sq = r["qty"] if r["side"] == "LONG" else -r["qty"]
            running += sq
            ts_iso = pd.to_datetime(r["ts"]).isoformat()
            if r["side"] == "LONG":
                long_x.append(ts_iso); long_y.append(r["price"]); long_cd.append([r["qty"], running])
            else:
                short_x.append(ts_iso); short_y.append(r["price"]); short_cd.append([r["qty"], running])

    data = {
        "t": [x.isoformat() for x in t],
        "o": ohlc["open"].tolist(), "h": ohlc["high"].tolist(),
        "l": ohlc["low"].tolist(), "c": ohlc["close"].tolist(),
        "eq": [round(v, 2) for v in eq.tolist()],
        "pos": [round(v, 6) for v in pos.tolist()],
        "bands": bands,
        "longEntries": {"x": long_x, "y": long_y, "cd": long_cd},
        "shortEntries": {"x": short_x, "y": short_y, "cd": short_cd},
    }

    m = result.metrics
    title = (f"Kraken Futures BTC/USD 1d — {cfg.name} replay  "
             f"({t[0]:%Y-%m-%d} → {t[-1]:%Y-%m-%d}, {len(t)} bars)")
    summary = (f"trades {len(trades)} · end ${eq.iloc[-1]:,.0f} "
               f"({eq.iloc[-1]/eq.iloc[0]-1:+.1%}) · Sharpe {m.sharpe:.2f} · maxDD {m.max_drawdown:.1%}")

    html = (HTML_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__SUMMARY__", summary)
            .replace("__NLONG__", str(n_long))
            .replace("__NSHORT__", str(n_short))
            .replace("__NFLAT__", str(n_flat))
            .replace("__DATA__", json.dumps(data)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html)

    print(f"Replay over {len(bars)} bars ({t[0]:%Y-%m-%d} → {t[-1]:%Y-%m-%d})")
    print(f"trades={len(trades)}  end=${eq.iloc[-1]:,.0f}  LONG={n_long} SHORT={n_short} FLAT={n_flat}")
    print(f"interactive chart -> {args.out}  (open in a browser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
