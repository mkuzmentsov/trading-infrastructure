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

    for name, help_ in [
        ("validate", "run the validation harness + approve-for-live gate"),
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        return _cmd_fetch(args)
    if args.command == "backtest":
        return _cmd_backtest(args)
    raise SystemExit(f"`atb {args.command}` is not implemented yet (scaffold).")


if __name__ == "__main__":
    sys.exit(main())
