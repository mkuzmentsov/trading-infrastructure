"""Compare math_smart (v1) vs math_smart_v2 over a list of bundles.

Runs each variant in a subprocess so module-level env-driven constants reload.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
V1_YAML = SCRIPT_DIR.parent / "bots" / "pm_btc_smart.yaml"
V2_YAML = SCRIPT_DIR.parent / "bots" / "pm_btc_smart_v2.yaml"

BUNDLES = [
    "pm-btc-logs_pm-btc-smart_20260421_154123",
    "pm-btc-logs_pm-btc-smart_20260421_091646_big",
    "pm-btc-logs_pm-btc-3_20260420_075109",
    "pm-btc-logs_pm-btc-3_20260419_101700",
]

CHILD = r"""
import json, os, sys
from pathlib import Path
SCRIPT_DIR = Path(sys.argv[1])
yaml_path = sys.argv[2]
bundle = sys.argv[3]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'files' / 'scripts'))
sys.path.insert(0, str(SCRIPT_DIR / 'files' / 'scripts' / 'strategies'))
from backtest import apply_yaml_to_env, load_config
apply_yaml_to_env(yaml_path)
# Allow env overrides from parent to win over YAML for knobs we're sweeping.
for k in ('SMART_V2_MODE',):
    v = os.environ.get('_OVR_' + k)
    if v is not None:
        os.environ[k] = v
from strategies.bundle_backtest import BundleBacktestRunner
cfg = load_config(yaml_path)
runner = BundleBacktestRunner(cfg=cfg)
result = runner.run_tick_strategy(bundle)
trades = result.trades
n = len(trades)
wins = sum(1 for t in trades if t.pnl > 0)
pnl = sum(t.pnl for t in trades)
invested = sum(t.entry_price * t.shares for t in trades)
out = {
    'n': n,
    'wins': wins,
    'wr': round(wins / max(1, n), 3),
    'pnl': round(pnl, 2),
    'invested': round(invested, 2),
    'roi_pct': round((pnl / max(1e-9, invested)) * 100, 1),
}
print('__RESULT__' + json.dumps(out))
"""


def run(yaml_path: Path, bundle: Path, mode_override: str | None = None) -> dict:
    env = dict(os.environ)
    if mode_override is not None:
        env["_OVR_SMART_V2_MODE"] = mode_override
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, str(SCRIPT_DIR), str(yaml_path), str(bundle)],
        capture_output=True, text=True, timeout=300, env=env,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-400:]}
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return json.loads(line[len("__RESULT__"):])
    return {"error": "no result line"}


VARIANTS = [
    ("v1",            V1_YAML, None),
    ("v2-haircut",    V2_YAML, "haircut"),
    ("v2-forecast",   V2_YAML, "forecast"),
    ("v2-chainlink",  V2_YAML, "chainlink_ref"),
]


def fmt(r: dict) -> str:
    if "error" in r:
        return f"ERR:{r['error'][:30]}"
    return f"{r['n']:>4} {r['wr']:>5.2f} ${r['pnl']:>+8.2f} {r['roi_pct']:>+6.1f}%"


def main() -> None:
    header = f"{'bundle':<48}"
    for label, _, _ in VARIANTS:
        header += f" {label:>26}"
    print(header)
    print("-" * len(header))
    totals = {label: {"n": 0, "pnl": 0.0, "inv": 0.0, "w": 0} for label, _, _ in VARIANTS}
    for name in BUNDLES:
        bundle = SCRIPT_DIR / name
        row = f"{name:<48}"
        for label, yaml, mode in VARIANTS:
            r = run(yaml, bundle, mode_override=mode)
            row += f" {fmt(r):>26}"
            if "error" not in r:
                t = totals[label]
                t["n"] += r["n"]; t["pnl"] += r["pnl"]; t["inv"] += r["invested"]; t["w"] += r["wins"]
        print(row)
    print("-" * len(header))
    total_row = f"{'TOTAL':<48}"
    for label, _, _ in VARIANTS:
        t = totals[label]
        wr = t["w"] / max(1, t["n"])
        roi = (t["pnl"] / max(1e-9, t["inv"])) * 100
        cell = f"{t['n']:>4} {wr:>5.2f} ${t['pnl']:>+8.2f} {roi:>+6.1f}%"
        total_row += f" {cell:>26}"
    print(total_row)


if __name__ == "__main__":
    main()
