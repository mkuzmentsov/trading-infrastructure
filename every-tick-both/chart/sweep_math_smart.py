#!/usr/bin/env python3
"""Parameter sweep for math_smart on specified bundles.

Usage:
    python3 sweep_math_smart.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "files" / "scripts"))
sys.path.insert(0, str(SCRIPT_DIR / "files" / "scripts" / "strategies"))

TARGET_BUNDLES = [
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260419_101700",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260420_075109",
]
VALIDATION_BUNDLES = [
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260418_224248",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_101755",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_155128",
]

YAML_PATH = SCRIPT_DIR.parent / "bots" / "pm_btc_smart.yaml"


def _load_yaml_env() -> dict[str, str]:
    """Get the YAML baseline as an env dict (camelCase -> UPPER_SNAKE_CASE)."""
    import re
    camel_re = re.compile(r"(?<!^)(?=[A-Z])")
    with open(YAML_PATH) as handle:
        raw = yaml.safe_load(handle) or {}
    bot = raw.get("bot", {}) or {}
    env = {}
    for key, value in bot.items():
        if value is None:
            continue
        env_key = camel_re.sub("_", key).upper()
        env[env_key] = str(value)
    return env


BASE_ENV = _load_yaml_env()


def _run_with_env(bundle: Path, overrides: dict[str, str]) -> dict[str, Any]:
    """Run one backtest with given env overrides. Subprocess so module-level
    constants get re-loaded with new env vars."""
    import json
    import subprocess

    env = dict(os.environ)
    # Baseline yaml values first, then overrides win
    for k, v in BASE_ENV.items():
        env[k] = v
    for k, v in overrides.items():
        env[k] = v

    child = """
import json, sys
from pathlib import Path
bundle = Path(sys.argv[1])
scripts = Path(sys.argv[2])
sys.path.insert(0, str(scripts / 'files' / 'scripts'))
sys.path.insert(0, str(scripts / 'files' / 'scripts' / 'strategies'))
sys.path.insert(0, str(scripts))
from strategies.bundle_backtest import BundleBacktestRunner
from backtest import load_config

# Build cfg from env (no yaml; env overrides already applied).
# Re-use load_config by pointing at a temp yaml? Easier: call with cfg dict.
# Minimum required keys for BundleBacktestRunner: STRATEGY_NAME.
import os
cfg = {
    'STRATEGY_NAME': os.environ.get('STRATEGY_NAME', 'math_smart'),
    'ENTRY_CONFIRMATION_TICKS': int(os.environ.get('ENTRY_CONFIRMATION_TICKS', '1')),
    'ENTRY_MIN_SECONDS_LEFT': int(os.environ.get('ENTRY_MIN_SECONDS_LEFT', '20')),
    'STOP_LOSS_MARKET_LIMIT': int(os.environ.get('STOP_LOSS_MARKET_LIMIT', '1')),
    'TRAILING_ARM_GAIN': float(os.environ.get('TRAILING_ARM_GAIN', '0.99')),
    'TRAILING_STOP_GAP': float(os.environ.get('TRAILING_STOP_GAP', '0.05')),
    'TAKE_PROFIT': float(os.environ.get('TAKE_PROFIT', '0.90')),
    'STOP_LOSS': float(os.environ.get('STOP_LOSS', '0.90')),
    'SL_ARM_DELAY_SECS': float(os.environ.get('SL_ARM_DELAY_SECS', '60')),
    'SL_MIN_ADVERSE_BTC': float(os.environ.get('SL_MIN_ADVERSE_BTC', '0.0015')),
    'ULTRA_CHEAP_SL_DELAY_SECS': float(os.environ.get('ULTRA_CHEAP_SL_DELAY_SECS', '120')),
}
runner = BundleBacktestRunner(cfg=cfg)
result = runner.run_tick_strategy(str(bundle))
wins = sum(1 for t in result.trades if t.pnl > 0)
losses = sum(1 for t in result.trades if t.pnl <= 0)
out = {
    'n': len(result.trades),
    'pnl': round(sum(t.pnl for t in result.trades), 2),
    'wins': wins,
    'losses': losses,
    'wr': round(wins / max(1, len(result.trades)), 3),
    'avg_win': round(sum(t.pnl for t in result.trades if t.pnl > 0) / max(1, wins), 3),
    'avg_loss': round(sum(t.pnl for t in result.trades if t.pnl <= 0) / max(1, losses), 3),
}
print(json.dumps(out))
"""
    proc = subprocess.run(
        [sys.executable, "-c", child, str(bundle), str(SCRIPT_DIR)],
        capture_output=True, env=env, text=True, timeout=180,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-800:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": f"parse: {e} -- {proc.stdout[-400:]}"}


def run_config(label: str, overrides: dict[str, str], bundles: list[Path]) -> dict:
    per = []
    total_pnl = 0.0
    total_n = 0
    total_w = 0
    for b in bundles:
        r = _run_with_env(b, overrides)
        if "error" in r:
            print(f"  [{b.name}] ERROR: {r['error']}")
            continue
        per.append((b.name, r))
        total_pnl += r["pnl"]
        total_n += r["n"]
        total_w += r["wins"]
    wr = total_w / max(1, total_n)
    agg = {"label": label, "n": total_n, "pnl": round(total_pnl, 2), "wr": round(wr, 3)}
    print(f"\n=== {label} ===  overrides={overrides}")
    for name, r in per:
        print(f"  {name}: n={r['n']:3d} pnl={r['pnl']:+7.2f} wr={r['wr']:.2f} "
              f"avg_w={r['avg_win']:+.2f} avg_l={r['avg_loss']:+.2f}")
    print(f"  TOTAL: n={agg['n']} pnl=${agg['pnl']:+.2f} wr={agg['wr']:.2%}")
    return {"label": label, "overrides": overrides, "per": per, "agg": agg}


def main():
    print("=" * 70)
    print("STEP 1: Baseline on target bundles")
    print("=" * 70)
    base = run_config("baseline", {}, TARGET_BUNDLES)

    print("\n" + "=" * 70)
    print("STEP 2: Single-parameter sweeps")
    print("=" * 70)

    hyps = [
        ("H1a_min_z_late=1.0",     {"SMART_MIN_Z_LATE": "1.0"}),
        ("H1b_min_z_late=1.2",     {"SMART_MIN_Z_LATE": "1.2"}),
        ("H1c_min_z_late=1.5",     {"SMART_MIN_Z_LATE": "1.5"}),
        ("H2a_disable_late_ovr",   {"SMART_LATE_FLOOR": "0.30", "SMART_LATE_CEIL": "0.70"}),
        ("H2b_tighten_late_ovr",   {"SMART_LATE_FLOOR": "0.20", "SMART_LATE_OVERRIDE_Z": "3.0"}),
        ("H3a_book_div=0.04",      {"SMART_MIN_BOOK_DIVERGENCE": "0.04"}),
        ("H3b_book_div=0.05",      {"SMART_MIN_BOOK_DIVERGENCE": "0.05"}),
        ("H3c_book_div=0.06",      {"SMART_MIN_BOOK_DIVERGENCE": "0.06"}),
        ("H5_confirm=2",           {"ENTRY_CONFIRMATION_TICKS": "2"}),
        ("H6a_ceil=0.65",          {"SMART_ENTRY_CEIL": "0.65"}),
        ("H6b_ceil=0.60",          {"SMART_ENTRY_CEIL": "0.60"}),
        ("H7a_thesis=0.0015",      {"SMART_THESIS_BREAK_BTC": "0.0015"}),
        ("H7b_thesis=0.0025",      {"SMART_THESIS_BREAK_BTC": "0.0025"}),
        ("H8a_min_edge=0.04",      {"SMART_MIN_EDGE": "0.04"}),
        ("H8b_min_edge=0.05",      {"SMART_MIN_EDGE": "0.05"}),
        ("H9a_z_early=2.0",        {"SMART_MIN_Z_EARLY": "2.0"}),
        ("H9b_z_early=2.5",        {"SMART_MIN_Z_EARLY": "2.5"}),
        ("H10_floor=0.35",         {"SMART_ENTRY_FLOOR": "0.35"}),
    ]

    sweep_results = [base]
    for label, ov in hyps:
        r = run_config(label, ov, TARGET_BUNDLES)
        sweep_results.append(r)

    print("\n" + "=" * 70)
    print("RANKED SUMMARY (target bundles)")
    print("=" * 70)
    ranked = sorted(sweep_results, key=lambda r: r["agg"]["pnl"], reverse=True)
    for r in ranked:
        a = r["agg"]
        print(f"  {a['label']:30s} pnl=${a['pnl']:+7.2f}  n={a['n']:3d}  wr={a['wr']:.2%}")


if __name__ == "__main__":
    main()
