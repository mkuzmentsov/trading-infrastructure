#!/usr/bin/env python3
"""Sweep config overrides on the pm_btc_3 bundles and report aggregate PnL.

Each variant runs in its own subprocess so strategy modules freeze env fresh.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLES = sorted(str(p) for p in HERE.glob("pm-btc-logs_pm-btc-3_*"))
BASELINE_YAML = str(HERE.parent / "bots" / "pm_btc_3.yaml")


VARIANTS: list[tuple[str, dict[str, str]]] = [
    ("baseline", {}),
    ("minPrice_040", {"MIN_ENTRY_PRICE": "0.40"}),
    ("minPrice_045", {"MIN_ENTRY_PRICE": "0.45"}),
    ("minPrice_050", {"MIN_ENTRY_PRICE": "0.50"}),
    ("gate_th_065", {"ENTRY_GATE_THRESHOLD": "0.65"}),
    ("gate_th_070", {"ENTRY_GATE_THRESHOLD": "0.70"}),
    ("gateMin_040_noCheap", {
        "ENTRY_GATE_MIN_PRICE": "0.40",
        "ENTRY_GATE_CHEAP_OVERRIDE_SCORE": "0.99",  # effectively disable
    }),
    ("gateMin_045_noCheap", {
        "ENTRY_GATE_MIN_PRICE": "0.45",
        "ENTRY_GATE_CHEAP_OVERRIDE_SCORE": "0.99",
    }),
    ("minPrice_045_gate_065", {
        "MIN_ENTRY_PRICE": "0.45",
        "ENTRY_GATE_THRESHOLD": "0.65",
    }),
    ("minPrice_045_gate_070_edge_007", {
        "MIN_ENTRY_PRICE": "0.45",
        "ENTRY_GATE_THRESHOLD": "0.70",
        "MIN_EDGE": "0.07",
    }),
    ("entry_secs_60_minPrice_045", {
        "ENTRY_MIN_SECONDS_LEFT": "60",
        "MIN_ENTRY_PRICE": "0.45",
    }),
    ("minPrice_050_gate_070", {
        "MIN_ENTRY_PRICE": "0.50",
        "ENTRY_GATE_THRESHOLD": "0.70",
    }),
]

WORKER = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(os.environ['PM_BOT_DIR']) / 'files' / 'scripts'))
sys.path.insert(0, str(Path(os.environ['PM_BOT_DIR'])))
from backtest import apply_yaml_to_env
apply_yaml_to_env(os.environ['PM_BASELINE_YAML'])
# Apply variant overrides after the baseline YAML so they win
for k, v in json.loads(os.environ['PM_OVERRIDES']).items():
    os.environ[k] = v
from strategies.bundle_backtest import BundleBacktestRunner
runner = BundleBacktestRunner(cfg=None, yaml_path=os.environ['PM_BASELINE_YAML'])
# Also apply overrides to runner.cfg (used for bundle_backtest's own pre-strategy gates)
for k, v in json.loads(os.environ['PM_OVERRIDES']).items():
    try:
        runner.cfg[k] = type(runner.cfg.get(k, v))(v)
    except Exception:
        runner.cfg[k] = v
totals = {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0,
          'cheap_entries': 0, 'cheap_pnl': 0.0, 'cheap_losses': 0}
for bundle in os.environ['PM_BUNDLES'].split(','):
    result = runner.run_direct_strategy(bundle)
    for t in result.trades:
        totals['trades'] += 1
        totals['pnl'] += t.pnl
        if t.pnl > 0:
            totals['wins'] += 1
        else:
            totals['losses'] += 1
        if t.entry_price < 0.45:
            totals['cheap_entries'] += 1
            totals['cheap_pnl'] += t.pnl
            if t.pnl <= 0:
                totals['cheap_losses'] += 1
print(json.dumps(totals))
"""


def run_variant(name: str, overrides: dict[str, str]) -> dict:
    env = os.environ.copy()
    env["PM_BOT_DIR"] = str(HERE)
    env["PM_BASELINE_YAML"] = BASELINE_YAML
    env["PM_BUNDLES"] = ",".join(BUNDLES)
    env["PM_OVERRIDES"] = json.dumps(overrides)
    proc = subprocess.run(
        [sys.executable, "-c", WORKER],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(HERE),
    )
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[-500:]}
    out = proc.stdout.strip().splitlines()
    return json.loads(out[-1])


def main() -> int:
    print(f"Bundles: {len(BUNDLES)}")
    for b in BUNDLES:
        print(f"  {Path(b).name}")
    print()
    print(f"{'variant':35s} {'pnl':>8s} {'trades':>7s} {'wr':>5s}  {'cheap':>6s} {'cheapPnL':>9s}")
    print("-" * 80)
    for name, overrides in VARIANTS:
        res = run_variant(name, overrides)
        if "error" in res:
            print(f"{name:35s} ERROR: {res['error']}")
            continue
        wr = res["wins"] / res["trades"] if res["trades"] else 0.0
        print(
            f"{name:35s} {res['pnl']:>+8.2f} {res['trades']:>7d} {wr*100:>4.0f}%  "
            f"{res['cheap_entries']:>6d} {res['cheap_pnl']:>+9.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
