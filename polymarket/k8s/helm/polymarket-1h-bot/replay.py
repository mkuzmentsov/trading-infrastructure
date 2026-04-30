#!/usr/bin/env python3
"""Production-fidelity replay for the 1h bot.

Runs the same `BundleBacktestRunner` that drives the 5m bot's tuning, but for
the 1h chart. Compares two configs over one bundle:

  - "gates_on"  — current values.yaml as-is (new salvage stops enabled)
  - "gates_off" — env overrides forcing the 4 new stops back to 0 (= prior live behaviour)

Each run is a subprocess so module-level env-driven constants reload.

Usage:  ./replay.py [bundle_dir]
        bundle_dir defaults to the most recent 1h bundle under polymarket/logs/1h/.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CHART_DIR = Path(__file__).resolve().parent
HELM_DIR = CHART_DIR.parent
REPO_ROOT = CHART_DIR.parents[3]
LOGS_DIR = REPO_ROOT / "polymarket" / "logs" / "1h"
VALUES_YAML = CHART_DIR / "values.yaml"
BOT_YAML = HELM_DIR / "bots" / "pm_btc_1h_smart.yaml"

# Env keys we override in the "gates_off" baseline run.
GATES_OFF = {
    "SMART_SALVAGE_BID_FLOOR": "0",
    "SMART_SALVAGE_BID_VELOCITY_DROP": "0",
    "SMART_SALVAGE_BID_VELOCITY_WINDOW": "3",
    "SMART_THESIS_BREAK_SIGMA_MULT": "0",
}

CHILD = r"""
import json, os, sys
from pathlib import Path

chart_dir = Path(sys.argv[1])
values_yaml = sys.argv[2]
bot_yaml = sys.argv[3]
bundle = sys.argv[4]

sys.path.insert(0, str(chart_dir))
sys.path.insert(0, str(chart_dir / 'files' / 'scripts'))
sys.path.insert(0, str(chart_dir / 'files' / 'scripts' / 'strategies'))

from backtest import apply_yaml_to_env, load_config

# Apply bot override first (sets env), then chart values fills defaults
# (apply_yaml_to_env skips keys already in os.environ). Caller-set env wins
# over both since they're already in os.environ before this runs.
apply_yaml_to_env(bot_yaml)
apply_yaml_to_env(values_yaml)

from strategies.bundle_backtest import BundleBacktestRunner

cfg = load_config(values_yaml)  # cfg dict only used for replay metadata
runner = BundleBacktestRunner(cfg=cfg, yaml_path=values_yaml)
result = runner.run(bundle)

trades = result.trades
out = {
    'n': len(trades),
    'wins': sum(1 for t in trades if t.pnl > 0),
    'pnl': round(sum(t.pnl for t in trades), 4),
    'invested': round(sum(t.entry_price * t.shares for t in trades), 2),
    'trades': [
        {
            'ts': round(t.ts, 1),
            'cid': t.condition_id[:14],
            'dir': t.direction,
            'reason': t.exit_reason,
            'entry': round(t.entry_price, 4),
            'exit': round(t.exit_price, 4),
            'pnl': round(t.pnl, 2),
            'shares': t.shares,
            'secs_left': t.seconds_left,
        }
        for t in trades
    ],
    # Show what env actually drove the strategy
    'env_dump': {
        k: os.environ.get(k, '<unset>')
        for k in (
            'SMART_SALVAGE_BID_FLOOR',
            'SMART_SALVAGE_BID_VELOCITY_DROP',
            'SMART_SALVAGE_BID_VELOCITY_WINDOW',
            'SMART_SALVAGE_SECS',
            'SMART_THESIS_BREAK_SIGMA_MULT',
            'SMART_THESIS_BREAK_SECS',
            'SMART_FORCE_EXIT_SECS',
            'SMART_LATE_SKIM_SECS',
        )
    },
}
print('__RESULT__' + json.dumps(out))
"""


def run(label: str, extra_env: dict[str, str] | None = None, bundle: str = "") -> dict:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, str(CHART_DIR), str(VALUES_YAML), str(BOT_YAML), bundle],
        capture_output=True, text=True, timeout=600, env=env,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:], "label": label}
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            r = json.loads(line[len("__RESULT__"):])
            r["label"] = label
            return r
    return {"error": "no result line", "stdout": proc.stdout[-2000:], "label": label}


def fmt_summary(r: dict) -> str:
    if "error" in r:
        return f"[{r['label']}] ERROR: {r['error'][:300]}"
    n, w, pnl, inv = r["n"], r["wins"], r["pnl"], r["invested"]
    wr = w / max(1, n)
    roi = (pnl / max(1e-9, inv)) * 100
    return f"[{r['label']:<10}] trades={n:>3}  wins={w:>3}  WR={wr:>5.1%}  PnL=${pnl:+8.2f}  invested=${inv:>7.2f}  ROI={roi:+6.1f}%"


def fmt_trade(t: dict) -> str:
    return (f"  {t['ts']:>14.1f}  {t['cid']:<16}  {t['dir']:<4}  {t['reason']:<22}  "
            f"entry={t['entry']:>5.2f}  exit={t['exit']:>5.2f}  sh={t['shares']:>2}  "
            f"sLeft={t['secs_left']:>4}  pnl=${t['pnl']:+6.2f}")


def diff_trades(a: dict, b: dict) -> None:
    """Pair trades by (ts, cid, dir) and show side-by-side."""
    if "error" in a or "error" in b:
        return
    print()
    print("Per-trade comparison (matched by entry ts + condition_id + direction):")
    print(f"{'entry_ts':<13}  {'cid':<16}  {'dir':<4}  "
          f"{'gates_off reason':<22} -> {'gates_on reason':<22}  "
          f"{'off pnl':>8}  {'on pnl':>8}  {'Δ':>8}")
    by_key_a = {(t["ts"], t["cid"], t["dir"]): t for t in a["trades"]}
    by_key_b = {(t["ts"], t["cid"], t["dir"]): t for t in b["trades"]}
    keys = sorted(set(by_key_a) | set(by_key_b))
    for k in keys:
        ta = by_key_a.get(k)
        tb = by_key_b.get(k)
        if ta and tb:
            delta = tb["pnl"] - ta["pnl"]
            mark = "  " if abs(delta) < 0.01 else ("✓ " if delta > 0 else "✗ ")
            print(f"{mark}{ta['ts']:<13.1f}  {ta['cid']:<16}  {ta['dir']:<4}  "
                  f"{ta['reason']:<22} -> {tb['reason']:<22}  "
                  f"{ta['pnl']:>+8.2f}  {tb['pnl']:>+8.2f}  {delta:>+8.2f}")
        elif ta:
            print(f"-- {ta['ts']:<13.1f}  {ta['cid']:<16}  {ta['dir']:<4}  "
                  f"{ta['reason']:<22} -> {'(no trade)':<22}  "
                  f"{ta['pnl']:>+8.2f}    {'-':>8}    {'-':>8}")
        else:
            print(f"++ {tb['ts']:<13.1f}  {tb['cid']:<16}  {tb['dir']:<4}  "
                  f"{'(no trade)':<22} -> {tb['reason']:<22}  "
                  f"{'-':>8}  {tb['pnl']:>+8.2f}    {'-':>8}")


def main() -> int:
    if len(sys.argv) >= 2:
        bundle = sys.argv[1]
    else:
        candidates = sorted([p for p in LOGS_DIR.iterdir() if p.is_dir() and p.name.startswith("pm-btc-logs_")])
        if not candidates:
            print(f"No bundles in {LOGS_DIR}", file=sys.stderr)
            return 1
        bundle = str(candidates[-1])

    print(f"Bundle:     {bundle}")
    print(f"Chart:      {CHART_DIR}")
    print(f"Values:     {VALUES_YAML}")
    print(f"Override:   {BOT_YAML}")
    print()

    print("Running gates_off baseline (4 new stops forced to 0)...")
    off = run("gates_off", extra_env=GATES_OFF, bundle=bundle)
    print(fmt_summary(off))
    if "error" in off:
        print(off["error"], file=sys.stderr)
        return 2

    print()
    print("Running gates_on (current values.yaml)...")
    on = run("gates_on", extra_env=None, bundle=bundle)
    print(fmt_summary(on))
    if "error" in on:
        print(on["error"], file=sys.stderr)
        return 2

    print()
    print("Env actually applied per run (selected keys):")
    for label, r in (("gates_off", off), ("gates_on", on)):
        print(f"  {label}:")
        for k, v in r["env_dump"].items():
            print(f"    {k:<35} = {v}")

    print()
    print("=" * 100)
    print(fmt_summary(off))
    print(fmt_summary(on))
    delta = on["pnl"] - off["pnl"]
    print(f"  Δ PnL = ${delta:+.2f}  (positive = gates_on better)")

    diff_trades(off, on)
    return 0


if __name__ == "__main__":
    sys.exit(main())
