#!/usr/bin/env python3
"""Count exit-reason distribution across bundles for math_smart."""
from __future__ import annotations
import os, sys, json, subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BUNDLES = [
    "pm-btc-logs_pm-btc-3_20260419_101700",
    "pm-btc-logs_pm-btc-3_20260420_075109",
    "pm-btc-logs_pm-btc-2_20260418_224248",
    "pm-btc-logs_pm-btc-2_20260419_101755",
    "pm-btc-logs_pm-btc-2_20260419_155128",
]

sys.path.insert(0, str(SCRIPT_DIR))
from sweep_math_smart import BASE_ENV

TUNED = {"SMART_ENTRY_FLOOR": "0.35", "SMART_LATE_FLOOR": "0.20", "SMART_LATE_OVERRIDE_Z": "3.0"}

child = r"""
import json, os, sys
from pathlib import Path
scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts / 'files' / 'scripts'))
sys.path.insert(0, str(scripts / 'files' / 'scripts' / 'strategies'))
sys.path.insert(0, str(scripts))
from strategies.bundle_backtest import BundleBacktestRunner
cfg = {
    'STRATEGY_NAME': 'math_smart',
    'ENTRY_CONFIRMATION_TICKS': 1,
    'ENTRY_MIN_SECONDS_LEFT': 20,
    'STOP_LOSS_MARKET_LIMIT': 1,
    'TRAILING_ARM_GAIN': 0.99, 'TRAILING_STOP_GAP': 0.05,
    'TAKE_PROFIT': 0.90, 'STOP_LOSS': 0.90,
    'SL_ARM_DELAY_SECS': 60, 'SL_MIN_ADVERSE_BTC': 0.0015,
    'ULTRA_CHEAP_SL_DELAY_SECS': 120,
}
r = BundleBacktestRunner(cfg=cfg).run_tick_strategy(sys.argv[2])
from collections import Counter
c = Counter(t.exit_reason for t in r.trades)
pnl_by = {}
for t in r.trades:
    pnl_by.setdefault(t.exit_reason, []).append(t.pnl)
out = {k: {"n": c[k], "pnl": round(sum(pnl_by[k]), 2), "avg": round(sum(pnl_by[k])/len(pnl_by[k]),2)} for k in c}
print(json.dumps(out))
"""

for bundle in BUNDLES:
    env = dict(os.environ)
    env.update(BASE_ENV)
    env.update(TUNED)
    proc = subprocess.run(
        [sys.executable, "-c", child, str(SCRIPT_DIR), str(SCRIPT_DIR / bundle)],
        env=env, capture_output=True, text=True, timeout=180,
    )
    print(f"\n=== {bundle} ===")
    if proc.returncode != 0:
        print("ERR:", proc.stderr[-400:]); continue
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    for reason, stats in sorted(data.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {reason:20s} n={stats['n']:3d}  pnl={stats['pnl']:+7.2f}  avg={stats['avg']:+.2f}")
