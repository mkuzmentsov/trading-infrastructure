"""Command-line entry point (`atb`).

Subcommands map to the §9 roadmap phases:

    atb fetch     --venue ... --symbols ...   ingest historical data (Phase 1)
    atb backtest  --config ...                run a backtest, write a report (Phase 2-3)
    atb validate  --config ...                run the §4 harness + approve-for-live gate (Phase 4)
    atb paper     --config ...                paper-trade against live data (Phase 6)
    atb live      --config ...                live, small capital (Phase 7) — guarded

Everything is config-driven so a run is reproducible (NFR2). `live` refuses to start
unless the model cleared the validation gate and a paper run has been recorded.
"""

from __future__ import annotations

import argparse
import sys


def _add_config_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", required=True, help="path to bot config (TOML/JSON)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atb", description="algo-trading-bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="ingest historical market + context data")
    p_fetch.add_argument("--venue", required=True, choices=["hyperliquid", "kraken"])
    p_fetch.add_argument("--symbols", required=True, nargs="+")
    p_fetch.add_argument("--interval", default="1h")
    p_fetch.add_argument("--start", required=True)
    p_fetch.add_argument("--end", required=True)

    for name, help_ in [
        ("backtest", "run a backtest and write a report"),
        ("validate", "run the validation harness + approve-for-live gate"),
        ("paper", "paper-trade against live data"),
        ("live", "run live (guarded: requires passed gate + paper run)"),
    ]:
        sp = sub.add_parser(name, help=help_)
        _add_config_arg(sp)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Dispatch is intentionally unimplemented in the scaffold; each branch wires to the
    # corresponding module (data.* / engine.backtest / validation.* / engine.live).
    raise NotImplementedError(f"command {args.command!r} not yet wired")


if __name__ == "__main__":
    sys.exit(main())
