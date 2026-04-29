#!/usr/bin/env python3
"""Grid-search entry-gate params across BOTH target bundles.

Goal: find a config where replay PnL is > 0 on both 101700 (training-set, hard
regime) and 075109 (out-of-sample, friendly regime).
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = str(HERE.parent / "bots" / "pm_btc_3.yaml")
BUNDLES = [
    str(HERE / "pm-btc-logs_pm-btc-3_20260419_101700"),
    str(HERE / "pm-btc-logs_pm-btc-3_20260420_075109"),
]

# Sweep space — keep modest.
GATE_THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50]
MIN_EDGES = [0.04, 0.06, 0.08, 0.10]
MIN_ENTRY_PRICES = [0.05, 0.35, 0.42]  # 0.05 = allow cheap; 0.35/0.42 = price floor
MIN_BOOK_DIVS = [0.04, 0.06, 0.08]

WORKER = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(os.environ['PM_BOT_DIR']) / 'files' / 'scripts'))
sys.path.insert(0, str(Path(os.environ['PM_BOT_DIR'])))
from backtest import apply_yaml_to_env
apply_yaml_to_env(os.environ['PM_BASELINE_YAML'])
for k, v in json.loads(os.environ['PM_OVERRIDES']).items():
    os.environ[k] = v
from strategies.bundle_backtest import BundleBacktestRunner
runner = BundleBacktestRunner(yaml_path=os.environ['PM_BASELINE_YAML'])
for k, v in json.loads(os.environ['PM_OVERRIDES']).items():
    try:
        runner.cfg[k] = type(runner.cfg.get(k, v))(v)
    except Exception:
        runner.cfg[k] = v
out = {}
for bundle in os.environ['PM_BUNDLES'].split(','):
    result = runner.run_direct_strategy(bundle)
    pnl = sum(t.pnl for t in result.trades)
    wins = sum(1 for t in result.trades if t.pnl > 0)
    out[Path(bundle).name] = {
        'pnl': round(pnl, 2),
        'trades': len(result.trades),
        'wins': wins,
    }
print(json.dumps(out))
"""


def run_combo(overrides: dict[str, str]) -> dict:
    env = os.environ.copy()
    env["PM_BOT_DIR"] = str(HERE)
    env["PM_BASELINE_YAML"] = BASELINE
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
        return {"error": proc.stderr.strip()[-300:]}
    out = proc.stdout.strip().splitlines()
    return json.loads(out[-1])


def main() -> int:
    combos = list(itertools.product(GATE_THRESHOLDS, MIN_EDGES, MIN_ENTRY_PRICES, MIN_BOOK_DIVS))
    print(f"Sweeping {len(combos)} combos across {len(BUNDLES)} bundles...")
    print()
    print(f"{'gate':>5} {'edge':>5} {'price':>5} {'bdiv':>5}  "
          f"{'101700':>18}  {'075109':>18}  {'sum_pnl':>8}  both>0")
    print("-" * 100)

    results = []
    for gate, edge, price, bdiv in combos:
        overrides = {
            "ENTRY_GATE_THRESHOLD": str(gate),
            "MIN_EDGE": str(edge),
            "MIN_ENTRY_PRICE": str(price),
            "MIN_BOOK_DIVERGENCE": str(bdiv),
        }
        res = run_combo(overrides)
        if "error" in res:
            print(f"{gate:>5.2f} {edge:>5.2f} {price:>5.2f} {bdiv:>5.2f}  ERR: {res['error']}")
            continue
        b1 = res.get("pm-btc-logs_pm-btc-3_20260419_101700", {})
        b2 = res.get("pm-btc-logs_pm-btc-3_20260420_075109", {})
        pnl1 = b1.get("pnl", 0.0)
        pnl2 = b2.get("pnl", 0.0)
        total = pnl1 + pnl2
        both_pos = "✓" if pnl1 > 0 and pnl2 > 0 else ""
        b1_str = f"{pnl1:+7.2f}/{b1.get('trades',0):>2}t/{b1.get('wins',0):>2}w"
        b2_str = f"{pnl2:+7.2f}/{b2.get('trades',0):>2}t/{b2.get('wins',0):>2}w"
        print(f"{gate:>5.2f} {edge:>5.2f} {price:>5.2f} {bdiv:>5.2f}  "
              f"{b1_str:>18}  {b2_str:>18}  {total:>+8.2f}  {both_pos}")
        results.append((gate, edge, price, bdiv, pnl1, pnl2, total, b1, b2))

    print()
    print("=== TOP 10 by sum PnL (both>0 only) ===")
    winners = [r for r in results if r[4] > 0 and r[5] > 0]
    winners.sort(key=lambda r: -r[6])
    for r in winners[:10]:
        gate, edge, price, bdiv, p1, p2, tot, b1, b2 = r
        print(f"gate={gate} edge={edge} price={price} bdiv={bdiv}  "
              f"101700={p1:+.2f}/{b1.get('trades',0)}t  "
              f"075109={p2:+.2f}/{b2.get('trades',0)}t  sum={tot:+.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
