"""Backtest the double-top/bottom pattern strategy on historical HL candles.

Replays candles bar-by-bar through the SAME pure functions the live bot uses
(`patterns.detect`, `strategy.plan_trade`, `strategy.check_exit`), so the sim
can't drift from live behaviour. Detection is causal — at each bar we only pass
candles up to that bar — so results are honest (no lookahead).

Fill model:
  - Enter at the confirmation bar's close (the bar that broke the neckline).
  - First exit opportunity is the NEXT bar (checked against its high/low).
  - Stop checked before target (a bar straddling both scores as a loss).
  - Round-trip cost = 2 × (taker_fee_bps + slippage_bps) on notional.

Usage:
    python3 pattern-bot/backtest.py [--coins BTC,ETH,SOL] [--interval 1h]
        [--config bot/config.yaml] [--trades] [--csv out.csv]

Pattern/risk params come from --config if given, else sensible defaults that
mirror config.example.yaml.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "bot"))
from patterns import PatternCfg, detect           # noqa: E402
from strategy import Position, RiskCfg, check_exit, plan_trade  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / "data"
START_EQUITY = 10_000.0


def chart_coin(coin: str, candles: list[dict], trades: list[dict], interval: str,
               out_path: Path) -> None:
    """Write an interactive HTML candlestick chart with each trade highlighted:
    a shaded zone over the hold period (green=long, red=short), entry/exit markers,
    and the stop/target levels — so trades can be eyeballed and verified."""
    import plotly.graph_objects as go

    df = pd.DataFrame(candles)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["dt"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name=coin, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        showlegend=False,
    ))

    # Shaded hold zones (one rectangle per trade, drawn beneath the candles).
    for tr in trades:
        long = tr["side"] == "long"
        fig.add_vrect(
            x0=tr["entry_dt"], x1=tr["exit_dt"], layer="below", line_width=0,
            fillcolor="#2ecc71" if long else "#e74c3c",
            opacity=0.10 if tr["pnl"] >= 0 else 0.06,
        )

    # Pattern formation: the candles that BUILT each pattern (1st peak/trough →
    # confirmation). Faint blue box over the formation span, the neckline segment,
    # and diamonds on the two peaks/troughs so you can see exactly what fired.
    hi = dict(zip(df["time"], df["high"]))
    lo = dict(zip(df["time"], df["low"]))
    neck_x, neck_y, pk_x, pk_y, pk_txt = [], [], [], [], []
    for tr in trades:
        if not tr.get("p1_time"):
            continue
        p1_dt = pd.to_datetime(tr["p1_time"], unit="ms", utc=True)
        conf_dt = tr["entry_dt"]   # confirmation bar == entry bar
        fig.add_vrect(x0=p1_dt, x1=conf_dt, layer="below", line_width=1,
                      line_color="#5dade2", fillcolor="#5dade2", opacity=0.05)
        neck_x += [p1_dt, conf_dt, None]
        neck_y += [tr["neckline"], tr["neckline"], None]
        for pt in (tr["p1_time"], tr["p2_time"]):
            price = hi.get(pt) if tr["side"] == "short" else lo.get(pt)
            if price is None:
                continue
            pk_x.append(pd.to_datetime(pt, unit="ms", utc=True))
            pk_y.append(float(price))
            pk_txt.append(f"{'peak' if tr['side'] == 'short' else 'trough'} {float(price):.6g}")
    if neck_x:
        fig.add_trace(go.Scatter(x=neck_x, y=neck_y, mode="lines", name="neckline",
                                 line=dict(color="#f39c12", width=1.5)))
    if pk_x:
        fig.add_trace(go.Scatter(x=pk_x, y=pk_y, mode="markers", name="pattern peaks/troughs",
                                 marker=dict(symbol="diamond", size=9, color="#f1c40f",
                                             line=dict(width=1, color="#222")),
                                 text=pk_txt, hoverinfo="text"))

    # Stop / target levels as dashed segments spanning each trade (single trace each,
    # None-separated, so they're one legend toggle and cheap to render).
    def _segments(level_key):
        xs, ys = [], []
        for tr in trades:
            xs += [tr["entry_dt"], tr["exit_dt"], None]
            ys += [tr[level_key], tr[level_key], None]
        return xs, ys

    sx, sy = _segments("stop")
    tx, ty = _segments("target")
    fig.add_trace(go.Scatter(x=sx, y=sy, mode="lines", name="stop",
                             line=dict(color="#c0392b", width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=tx, y=ty, mode="lines", name="target",
                             line=dict(color="#27ae60", width=1, dash="dot")))

    # Entry markers, split long/short. Exit markers, split win/loss.
    def _markers(pred, x_key, y_key, name, symbol, color, hover):
        sel = [tr for tr in trades if pred(tr)]
        if not sel:
            return
        fig.add_trace(go.Scatter(
            x=[tr[x_key] for tr in sel], y=[tr[y_key] for tr in sel],
            mode="markers", name=name,
            marker=dict(symbol=symbol, size=10, color=color,
                        line=dict(width=1, color="#222")),
            text=[hover(tr) for tr in sel], hoverinfo="text",
        ))

    def _entry_hover(tr):
        return (f"{tr['side'].upper()} entry @ {tr['entry']:.6g}<br>{tr['entry_dt']:%Y-%m-%d %H:%M}"
                f"<br>stop {tr['stop']:.6g} · target {tr['target']:.6g}")

    def _exit_hover(tr):
        return (f"EXIT {tr['reason']} @ {tr['exit']:.6g}<br>{tr['exit_dt']:%Y-%m-%d %H:%M}"
                f"<br>R={tr['R']:+.2f} · pnl=${tr['pnl']:+.2f} · held {tr['bars_held']}b")

    _markers(lambda t: t["side"] == "long", "entry_dt", "entry",
             "long entry", "triangle-up", "#2ecc71", _entry_hover)
    _markers(lambda t: t["side"] == "short", "entry_dt", "entry",
             "short entry", "triangle-down", "#e74c3c", _entry_hover)
    _markers(lambda t: t["pnl"] >= 0, "exit_dt", "exit",
             "exit (win)", "circle", "#1e8449", _exit_hover)
    _markers(lambda t: t["pnl"] < 0, "exit_dt", "exit",
             "exit (loss)", "x", "#922b21", _exit_hover)

    n_long = sum(1 for t in trades if t["side"] == "long")
    n_short = len(trades) - n_long
    fig.update_layout(
        title=f"{coin} {interval} — {len(trades)} trades ({n_long} long, {n_short} short)  "
              f"blue box=pattern · ◆=peaks/troughs · orange=neckline · ▲/▼ entry · ●/✕ exit · green/red=hold",
        xaxis_rangeslider_visible=False, template="plotly_dark",
        height=720, hovermode="closest",
    )
    fig.write_html(str(out_path), include_plotlyjs="cdn")


def _max_drawdown_frac(curve: np.ndarray) -> float:
    if len(curve) == 0:
        return 0.0
    peak = np.maximum.accumulate(curve)
    dd = (peak - curve) / peak
    return float(np.max(dd))


def backtest_coin(candles: list[dict], coin: str, pcfg: PatternCfg, rcfg: RiskCfg,
                  rt_cost_frac: float) -> dict:
    """Run one coin's backtest. Returns stats + the list of trades."""
    window = max(pcfg.max_bars_between + 2 * pcfg.pivot_lookback + 10, pcfg.trend_ma + 5)
    equity = START_EQUITY
    curve = [equity]
    pos: Position | None = None
    pending = None        # a detected signal awaiting fill at the NEXT bar's open
    last_ct: int | None = None
    trades: list[dict] = []

    for t in range(len(candles)):
        bar = candles[t]
        # 1) fill a pending signal at THIS bar's OPEN (the bar after the signal bar).
        #    This is the honest fill — you can't trade at a close that already printed —
        #    and it matches the live bot, which enters at the next available price.
        if pos is None and pending is not None:
            last_ct = pending.confirm_time          # mark acted regardless, so we don't re-eval it
            act = plan_trade(pending, bar["open"], equity, rcfg)
            if act is not None:
                pos = Position(
                    coin=coin, side=act["side"], size=act["size"],
                    entry_px=act["entry"], stop_px=act["stop"], target_px=act["target"],
                    confirm_time=pending.confirm_time, opened_time=bar["time"], bars_held=0,
                    p1_time=pending.p1_time, p2_time=pending.p2_time, neckline=pending.neckline,
                )
            pending = None

        # 2) manage an open position against THIS bar's range (may be the bar it opened on)
        if pos is not None:
            pos.bars_held += 1
            ex = check_exit(pos, bar["high"], bar["low"], rcfg)
            if ex is not None:
                reason, exit_px = ex
                if reason == "timeout":
                    exit_px = bar["close"]
                gross = (exit_px - pos.entry_px) if pos.side == "long" else (pos.entry_px - exit_px)
                pnl = gross * pos.size - pos.notional * rt_cost_frac * 2.0
                risk_dollars = abs(pos.entry_px - pos.stop_px) * pos.size
                equity += pnl
                trades.append({
                    "coin": coin, "side": pos.side, "pattern_time": pos.confirm_time,
                    "entry": pos.entry_px, "exit": exit_px, "reason": reason,
                    "stop": pos.stop_px, "target": pos.target_px,
                    "p1_time": pos.p1_time, "p2_time": pos.p2_time, "neckline": pos.neckline,
                    "pnl": pnl, "R": pnl / risk_dollars if risk_dollars > 0 else 0.0,
                    "bars_held": pos.bars_held,
                    "entry_dt": pd.to_datetime(pos.opened_time, unit="ms", utc=True),
                    "exit_dt": pd.to_datetime(bar["time"], unit="ms", utc=True),
                })
                pos = None
                curve.append(equity)

        # 3) detect a new signal only while flat and nothing already pending. The
        #    signal is queued and filled at the next bar's open (step 1).
        if pos is None and pending is None:
            w = candles[max(0, t - window + 1): t + 1]
            sig = detect(w, pcfg, coin=coin)
            if sig is not None and sig.confirm_time != last_ct:
                pending = sig

    curve_arr = np.array(curve, dtype=float)
    pnls = np.array([tr["pnl"] for tr in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    span_days = (candles[-1]["time"] - candles[0]["time"]) / 86_400_000 if len(candles) > 1 else 1.0
    total_ret = (equity - START_EQUITY) / START_EQUITY
    return {
        "coin": coin,
        "n_trades": len(trades),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "avg_R": float(np.mean([tr["R"] for tr in trades])) if trades else 0.0,
        "total_ret": total_ret,
        "ann_ret": total_ret * (365.0 / span_days) if span_days > 0 else 0.0,
        "max_dd": _max_drawdown_frac(curve_arr),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf") if wins.sum() > 0 else 0.0,
        "avg_hold": float(np.mean([tr["bars_held"] for tr in trades])) if trades else 0.0,
        "trades": trades,
    }


def _load_cfg(path: str | None) -> tuple[PatternCfg, RiskCfg, float]:
    if path and Path(path).exists():
        import yaml
        cfg = yaml.safe_load(Path(path).read_text()) or {}
    else:
        cfg = {}
    pcfg = PatternCfg.from_dict(cfg.get("pattern", {}))
    risk = cfg.get("risk", {}) or {}
    rcfg = RiskCfg.from_dict(risk)
    fee = float(risk.get("taker_fee_bps", 4.5))
    slip = float(risk.get("slippage_bps", 5.0))
    return pcfg, rcfg, (fee + slip) / 1e4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC,ETH,SOL")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--config", default=None, help="bot config.yaml for pattern/risk params (optional)")
    ap.add_argument("--trades", action="store_true", help="print every trade")
    ap.add_argument("--csv", default=None, help="write all trades to this CSV")
    # quick overrides for experimentation (e.g. hard SL/TP without editing config)
    ap.add_argument("--target-mode", choices=["measured_move", "fixed_rr", "pct"], default=None)
    ap.add_argument("--stop-loss-pct", type=float, default=None, help="hard stop %% from entry (target_mode pct), e.g. 0.20")
    ap.add_argument("--take-profit-pct", type=float, default=None, help="hard take-profit %% from entry (target_mode pct), e.g. 0.60")
    ap.add_argument("--max-hold-bars", type=int, default=None)
    ap.add_argument("--stop-height-frac", type=float, default=None, help="stop inside pattern, frac of height from neckline (0=beyond extreme); 0.5≈2:1 RR")
    ap.add_argument("--trend-ma", type=int, default=None, help="trend filter: short only below SMA(N), long only above (0=off)")
    ap.add_argument("--vol-confirm-mult", type=float, default=None, help="require breakout vol >= mult × pattern-avg vol (0=off)")
    ap.add_argument("--trough-depth", type=float, default=None, help="pattern: min neckline retrace from peaks (e.g. 0.008)")
    ap.add_argument("--peak-tol", type=float, default=None, help="pattern: max %% diff between the two peaks/troughs (e.g. 0.01)")
    ap.add_argument("--pivot-lookback", type=int, default=None, help="pattern: bars each side to qualify a swing pivot")
    ap.add_argument("--max-bars-between", type=int, default=None, help="pattern: max bars between the two peaks/troughs")
    ap.add_argument("--max-break-bars", type=int, default=None, help="pattern: break must occur within N bars of the 2nd peak (0=off)")
    ap.add_argument("--entry-mode", choices=["neckline_break", "second_peak"], default=None, help="pattern: when to enter")
    ap.add_argument("--max-trough-depth", type=float, default=None, help="pattern: reject troughs deeper than this (0=off), e.g. 0.10")
    ap.add_argument("--chart", action="store_true", help="write an interactive HTML chart per coin with trades highlighted")
    ap.add_argument("--chart-dir", default=str(Path(__file__).resolve().parent / "charts"))
    args = ap.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    pcfg, rcfg, rt_cost_frac = _load_cfg(args.config)
    import dataclasses
    over = {}
    if args.target_mode is not None: over["target_mode"] = args.target_mode
    if args.stop_loss_pct is not None: over["stop_loss_pct"] = args.stop_loss_pct
    if args.take_profit_pct is not None: over["take_profit_pct"] = args.take_profit_pct
    if args.max_hold_bars is not None: over["max_hold_bars"] = args.max_hold_bars
    if args.stop_height_frac is not None: over["stop_height_frac"] = args.stop_height_frac
    if over:
        rcfg = dataclasses.replace(rcfg, **over)
    pover = {}
    if args.trend_ma is not None: pover["trend_ma"] = args.trend_ma
    if args.vol_confirm_mult is not None: pover["vol_confirm_mult"] = args.vol_confirm_mult
    if args.trough_depth is not None: pover["min_trough_depth_pct"] = args.trough_depth
    if args.peak_tol is not None: pover["peak_tolerance_pct"] = args.peak_tol
    if args.pivot_lookback is not None: pover["pivot_lookback"] = args.pivot_lookback
    if args.max_bars_between is not None: pover["max_bars_between"] = args.max_bars_between
    if args.max_break_bars is not None: pover["max_break_bars"] = args.max_break_bars
    if args.entry_mode is not None: pover["entry_mode"] = args.entry_mode
    if args.max_trough_depth is not None: pover["max_trough_depth_pct"] = args.max_trough_depth
    if pover:
        pcfg = dataclasses.replace(pcfg, **pover)

    tgt = rcfg.target_mode
    if tgt == "pct":
        tgt = f"pct(SL={rcfg.stop_loss_pct:.0%},TP={rcfg.take_profit_pct:.0%})"
    elif tgt == "fixed_rr":
        tgt = f"fixed_rr({rcfg.fixed_rr:g})"
    print(f"[backtest] coins={coins} interval={args.interval}  "
          f"rt_cost={rt_cost_frac*1e4:.1f}bps/side×2  target={tgt}")
    print(f"           pattern: pivot_lookback={pcfg.pivot_lookback} tol={pcfg.peak_tolerance_pct:.0%} "
          f"gap=[{pcfg.min_bars_between},{pcfg.max_bars_between}] depth>={pcfg.min_trough_depth_pct:.0%}"
          f"  trend_ma={pcfg.trend_ma or 'off'} vol_mult={pcfg.vol_confirm_mult or 'off'}")
    print(f"           risk: {rcfg.risk_per_trade_pct:.2%}/trade maxL={rcfg.max_leverage}x "
          f"stop_buf={rcfg.stop_buffer_pct:.2%} max_hold={rcfg.max_hold_bars or '∞'}\n")

    print(f"{'coin':<6} {'trades':>6} {'win%':>6} {'avgR':>6} {'totRet%':>8} {'annRet%':>8} {'maxDD%':>7} {'PF':>6} {'avgHold':>8}")
    all_trades: list[dict] = []
    results = []
    for coin in coins:
        f = DATA_DIR / f"{coin}_{args.interval}.parquet"
        if not f.exists():
            print(f"{coin:<6} (no data — run fetch_data.py --coins {coin} --interval {args.interval})")
            continue
        df = pd.read_parquet(f).sort_values("time").reset_index(drop=True)
        cols = ["time", "open", "high", "low", "close"] + (["vol"] if "vol" in df.columns else [])
        candles = df[cols].to_dict("records")
        if len(candles) < 100:
            print(f"{coin:<6} (insufficient data: {len(candles)} bars)")
            continue
        r = backtest_coin(candles, coin, pcfg, rcfg, rt_cost_frac)
        results.append(r)
        all_trades.extend(r["trades"])
        pf = "inf" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
        print(f"{coin:<6} {r['n_trades']:>6} {r['win_rate']*100:>5.0f}% {r['avg_R']:>6.2f} "
              f"{r['total_ret']*100:>7.2f} {r['ann_ret']*100:>7.1f} {r['max_dd']*100:>6.1f} {pf:>6} {r['avg_hold']:>7.1f}")
        if args.chart:
            chart_dir = Path(args.chart_dir)
            chart_dir.mkdir(parents=True, exist_ok=True)
            out = chart_dir / f"{coin}_{args.interval}.html"
            chart_coin(coin, candles, r["trades"], args.interval, out)
            print(f"       chart -> {out}")

    if results:
        tp = np.array([tr["pnl"] for tr in all_trades], dtype=float)
        wins = tp[tp > 0]; losses = tp[tp < 0]
        n = len(all_trades)
        print("-" * 78)
        print(f"{'ALL':<6} {n:>6} {len(wins)/n*100 if n else 0:>5.0f}% "
              f"{np.mean([tr['R'] for tr in all_trades]) if n else 0:>6.2f} "
              f"{'':>8} {'':>8} {'':>7} "
              f"{(wins.sum()/abs(losses.sum())) if losses.sum() else float('nan'):>6.2f} "
              f"{np.mean([tr['bars_held'] for tr in all_trades]) if n else 0:>7.1f}")

    if args.trades:
        print("\n[trades]")
        for tr in sorted(all_trades, key=lambda t: t["entry_dt"]):
            print(f"  {tr['entry_dt']:%Y-%m-%d %H:%M} {tr['coin']:<5} {tr['side']:<5} "
                  f"entry={tr['entry']:.4g} exit={tr['exit']:.4g} {tr['reason']:<11} "
                  f"R={tr['R']:+.2f} pnl=${tr['pnl']:+.2f} held={tr['bars_held']}b")

    if args.csv and all_trades:
        pd.DataFrame(all_trades).to_csv(args.csv, index=False)
        print(f"\n[backtest] wrote {len(all_trades)} trades -> {args.csv}")


if __name__ == "__main__":
    main()
