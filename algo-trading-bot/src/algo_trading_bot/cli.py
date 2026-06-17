"""Command-line entry point (`atb`).

Subcommands map to the §9 roadmap phases:

    atb fetch     --venue ... --symbols ...   ingest historical data (Phase 1)
    atb backtest  --config ...                run a backtest, print a report (Phase 2-3)
    atb validate  --config ...                run the §4 harness + gate (Phase 4)   [stub]
    atb paper     --config ...                paper-trade against live data (Phase 6) [stub]
    atb live      --config ...                live, small capital (Phase 7)           [stub]

Everything is config-driven so a run is reproducible (NFR2).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_dt(s: str | None, default: datetime) -> datetime:
    if not s:
        return default
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _load_config(path: str):
    from .config import BotConfig

    text = Path(path).read_text()
    if path.endswith(".toml"):
        import tomllib

        data = tomllib.loads(text)
    else:
        import json

        data = json.loads(text)
    return BotConfig(**data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atb", description="algo-trading-bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="ingest historical market data")
    p_fetch.add_argument("--venue", required=True, help="ccxt venue id, e.g. binance/kraken/hyperliquid")
    p_fetch.add_argument("--symbols", required=True, nargs="+")
    p_fetch.add_argument("--interval", default="1h")
    p_fetch.add_argument("--start", required=True)
    p_fetch.add_argument("--end", default=None)
    p_fetch.add_argument("--data-dir", default="./data")

    p_bt = sub.add_parser("backtest", help="run a backtest and print a report")
    p_bt.add_argument("--config", required=True, help="path to bot config (TOML/JSON)")
    p_bt.add_argument("--start", default=None)
    p_bt.add_argument("--end", default=None)

    p_val = sub.add_parser("validate", help="in-sample tune -> OOS test + approve-for-live gate")
    p_val.add_argument("--config", required=True)
    p_val.add_argument("--start", default=None)
    p_val.add_argument("--end", default=None)
    p_val.add_argument("--train-frac", type=float, default=0.6)

    p_ml = sub.add_parser("metalabel", help="train meta-label GBT under purged CV; report OOS AUC")
    p_ml.add_argument("--config", required=True)
    p_ml.add_argument("--start", default=None)
    p_ml.add_argument("--end", default=None)
    p_ml.add_argument("--vertical-bars", type=int, default=24)

    for name, help_ in [
        ("paper", "paper-trade against live data"),
        ("live", "run live (guarded: requires passed gate + paper run)"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--config", required=True)

    return parser


def _cmd_fetch(args) -> int:
    from .data.fetch import fetch_to_store
    from .data.store import PointInTimeStore

    store = PointInTimeStore(args.data_dir)
    start = _parse_dt(args.start, datetime(2020, 1, 1, tzinfo=timezone.utc))
    end = _parse_dt(args.end, datetime.now(timezone.utc))
    print(f"Fetching {args.symbols} {args.interval} from {args.venue} "
          f"[{start:%Y-%m-%d} -> {end:%Y-%m-%d}] ...")
    n = fetch_to_store(store, args.venue, args.symbols, args.interval, start, end)
    print(f"Wrote {n} bars to {args.data_dir}/bars/")
    return 0


def _cmd_backtest(args) -> int:
    from .engine.backtest import Backtester

    cfg = _load_config(args.config)
    start = _parse_dt(args.start, datetime(2000, 1, 1, tzinfo=timezone.utc))
    end = _parse_dt(args.end, datetime.now(timezone.utc))
    result = Backtester(cfg).run(start, end)

    m = result.metrics
    eq = result.equity
    p = result.provenance
    ret_total = eq.iloc[-1] / eq.iloc[0] - 1 if len(eq) else 0.0
    print("\n=== Backtest report ===")
    print(f"universe={cfg.universe} venue={cfg.venue.name} interval={cfg.bar_interval}")
    print(f"bars={len(eq)}  {eq.index[0]:%Y-%m-%d} -> {eq.index[-1]:%Y-%m-%d}")
    print(f"start_equity={eq.iloc[0]:,.0f}  end_equity={eq.iloc[-1]:,.0f}  total_return={ret_total:+.1%}")
    print(f"trades={len(result.trades)}  turnover={m.turnover:.1f}x")
    print("-- metrics --")
    print(f"CAGR={m.cagr:+.1%}  vol={m.vol:.1%}  Sharpe={m.sharpe:.2f}  Sortino={m.sortino:.2f}")
    print(f"maxDD={m.max_drawdown:.1%} (dur {m.drawdown_duration} bars)  "
          f"hit={m.hit_rate:.1%}  PF={m.profit_factor:.2f}")
    print(f"skew={m.skew:+.2f}  kurtosis={m.kurtosis:+.2f}")
    print("-- provenance (§3.4) --")
    print(f"snapshot={p.data_snapshot_id}  commit={p.git_commit}  config={p.config_hash}")
    print("\nNote: one strategy, costs modeled. Beat this baseline OOS after costs "
          "before any ML ships (principle #4).")
    return 0


def _cmd_validate(args) -> int:
    from .validation.baseline_oos import run_oos_validation
    from .validation.gate import ApproveForLiveGate

    cfg = _load_config(args.config)
    start = _parse_dt(args.start, datetime(2000, 1, 1, tzinfo=timezone.utc))
    end = _parse_dt(args.end, datetime.now(timezone.utc))
    r = run_oos_validation(cfg, start, end, train_frac=args.train_frac)

    m = r.oos_metrics
    print("\n=== Validation (in-sample tune -> out-of-sample test) ===")
    print(f"universe={cfg.universe} interval={cfg.bar_interval}  grid_trials={r.n_trials}")
    print(f"OOS segment starts {r.split_ts:%Y-%m-%d} ({r.test_bars} bars after embargo)")
    print("-- in-sample selection --")
    print(f"best params={r.best_params}  train Sharpe={r.train_sharpe:.2f}")
    print("-- OUT-OF-SAMPLE (the number that counts) --")
    print(f"Sharpe={m.sharpe:.2f}  Sortino={m.sortino:.2f}  CAGR={m.cagr:+.1%}  maxDD={m.max_drawdown:.1%}")
    print(f"skew={m.skew:+.2f}  hit={m.hit_rate:.1%}  PF={m.profit_factor:.2f}")
    print(f"untuned-default OOS Sharpe={r.default_oos_sharpe:.2f}   buy&hold OOS Sharpe={r.buy_hold_oos_sharpe:.2f}")
    print(f"Deflated Sharpe (P[true SR>0], {r.n_trials} trials)={r.deflated_sharpe:.3f}")

    gate = ApproveForLiveGate(cfg.validation).evaluate(
        {"oos_sharpe": m.sharpe, "baseline_sharpe": 0.0, "deflated_sharpe": r.deflated_sharpe}
    )
    print("\n-- approve-for-live gate (§4) --")
    print(gate.summary())
    print("\nNote: PBO/CPCV, regime, stress and paper checks are not yet wired — this is a "
          "partial gate for the rule baseline. Full gate lands with the ML phase.")
    return 0


def _cmd_metalabel(args) -> int:
    from .engine.backtest import Backtester
    from .features.dataset import build_labeled_dataset
    from .model.metalabel import train_meta_label_cv

    cfg = _load_config(args.config)
    start = _parse_dt(args.start, datetime(2000, 1, 1, tzinfo=timezone.utc))
    end = _parse_dt(args.end, datetime.now(timezone.utc))

    bars = Backtester(cfg).load_bars(start, end)
    print(f"Building labeled dataset from {len(bars)} bars "
          f"(triple-barrier, vertical={args.vertical_bars} bars) ...")
    X, y, w, spans = build_labeled_dataset(
        bars, fast=cfg.trend.ema_fast, slow=cfg.trend.ema_slow,
        vol_window=cfg.trend.vol_window, vertical_bars=args.vertical_bars,
    )
    if len(X) < 500:
        raise SystemExit(f"only {len(X)} labeled events — fetch more history")

    res = train_meta_label_cv(
        X, y, w, spans,
        n_splits=cfg.validation.n_splits, embargo_pct=cfg.validation.embargo_pct,
    )
    print("\n=== Meta-label model (GBT, purged CV) ===")
    print(f"labeled events={len(X)}  features={res.n_features}  "
          f"folds={len(res.fold_aucs)}  fold AUCs={[round(a, 3) for a in res.fold_aucs]}")
    print(res.summary())
    edge = res.oos_auc - 0.5
    if res.oos_auc < 0.53:
        print(f"\nVerdict: OOS AUC {res.oos_auc:.3f} ~ coin-flip (edge {edge:+.3f}). The meta "
              "layer has no out-of-sample predictive power here, so it must NOT be wired into "
              "the book (principle #4). Fail fast — try other features/labels/horizons.")
    else:
        print(f"\nVerdict: OOS AUC {res.oos_auc:.3f} shows edge — next step: wire the model into "
              "MetaLabelMomentum and confirm it improves the baseline Sharpe OOS, after costs.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        return _cmd_fetch(args)
    if args.command == "backtest":
        return _cmd_backtest(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "metalabel":
        return _cmd_metalabel(args)
    raise SystemExit(f"`atb {args.command}` is not implemented yet (scaffold).")


if __name__ == "__main__":
    sys.exit(main())
