#!/usr/bin/env python3
"""Big multi-step sweep: exits ablation, new entry gates, shrinkage, sizing, direction, all-bundle validation."""
from __future__ import annotations
import sys, json, os, subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from sweep_math_smart import BASE_ENV  # YAML baseline env

TARGET_BUNDLES = [
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260419_101700",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260420_075109",
]
# Validation + larger robustness set. Dedup later if duplicates.
EXTRA_BUNDLES = [
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260418_224248",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_101755",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_155128",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260420_094934",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_195918",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_224258",
    SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_232058",
]
ALL_BUNDLES = TARGET_BUNDLES + EXTRA_BUNDLES

# Entry floor/late tuning winners carried over.
TUNED_ENTRY = {
    "SMART_ENTRY_FLOOR": "0.35",
    "SMART_LATE_FLOOR": "0.20",
    "SMART_LATE_OVERRIDE_Z": "3.0",
}


child_src = r"""
import json, os, sys
from pathlib import Path
scripts = Path(sys.argv[1])
bundle = sys.argv[2]
detail = os.environ.get('__DETAIL', '0') == '1'
sys.path.insert(0, str(scripts / 'files' / 'scripts'))
sys.path.insert(0, str(scripts / 'files' / 'scripts' / 'strategies'))
sys.path.insert(0, str(scripts))
from strategies.bundle_backtest import BundleBacktestRunner
cfg = {
    'STRATEGY_NAME': 'math_smart',
    'ENTRY_CONFIRMATION_TICKS': int(os.environ.get('ENTRY_CONFIRMATION_TICKS', '1')),
    'ENTRY_MIN_SECONDS_LEFT': 20, 'STOP_LOSS_MARKET_LIMIT': 1,
    'TRAILING_ARM_GAIN': 0.99, 'TRAILING_STOP_GAP': 0.05,
    'TAKE_PROFIT': 0.90, 'STOP_LOSS': 0.90,
    'SL_ARM_DELAY_SECS': 60, 'SL_MIN_ADVERSE_BTC': 0.0015,
    'ULTRA_CHEAP_SL_DELAY_SECS': 120,
}
r = BundleBacktestRunner(cfg=cfg).run_tick_strategy(bundle)
wins = sum(1 for t in r.trades if t.pnl > 0)
out = {
    'n': len(r.trades),
    'pnl': round(sum(t.pnl for t in r.trades), 2),
    'wr': round(wins / max(1, len(r.trades)), 3),
}
if detail:
    out['trades'] = [
        {
            'direction': t.direction, 'entry': t.entry_price, 'shares': int(t.shares),
            'edge': t.edge, 'p_up': t.p_up, 'exit_reason': t.exit_reason,
            'pnl': t.pnl, 'seconds_left': t.seconds_left,
        } for t in r.trades
    ]
print(json.dumps(out))
"""


def run_one(bundle: Path, overrides: dict, detail=False):
    env = dict(os.environ); env.update(BASE_ENV); env.update(overrides)
    if detail: env['__DETAIL'] = '1'
    else: env.pop('__DETAIL', None)
    proc = subprocess.run(
        [sys.executable, "-c", child_src, str(SCRIPT_DIR), str(bundle)],
        env=env, capture_output=True, text=True, timeout=240,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-500:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"error": f"parse {e}: {proc.stdout[-400:]}"}


def run_on(label: str, overrides: dict, bundles: list) -> dict:
    per = []
    tp = 0.0; tn = 0; tw = 0
    for b in bundles:
        r = run_one(b, overrides)
        if 'error' in r:
            print(f"  [{b.name}] ERR: {r['error']}"); continue
        per.append((b.name, r))
        tp += r['pnl']; tn += r['n']; tw += int(r['wr'] * r['n'] + 0.5)
    print(f"\n=== {label} === {overrides}")
    for name, r in per:
        print(f"  {name[:55]:55s} n={r['n']:3d} pnl={r['pnl']:+7.2f} wr={r['wr']:.2%}")
    agg = {'label': label, 'n': tn, 'pnl': round(tp, 2), 'wr': round(tw/max(1,tn), 3)}
    print(f"  TOTAL n={tn} pnl=${tp:+.2f} wr={agg['wr']:.2%}")
    return {'label': label, 'overrides': overrides, 'per': per, 'agg': agg}


def phase(name, cases, bundles):
    print("\n" + "=" * 72)
    print(f"PHASE: {name}")
    print("=" * 72)
    results = [run_on(lbl, ov, bundles) for lbl, ov in cases]
    print(f"\n--- Ranked ({name}) ---")
    for r in sorted(results, key=lambda r: r['agg']['pnl'], reverse=True):
        a = r['agg']
        print(f"  {a['label']:32s} pnl=${a['pnl']:+7.2f} n={a['n']:3d} wr={a['wr']:.2%}")
    return results


def main():
    # ---- PHASE 1: Exits ablation (on tuned entries) ----
    p1 = phase("1 · Exits ablation", [
        ("tuned_all_exits",        {**TUNED_ENTRY}),
        ("pure_hold",              {**TUNED_ENTRY, "SMART_DISABLE_EXITS": "1"}),
        ("no_profit_lock",         {**TUNED_ENTRY, "SMART_EXIT_PROFIT_LOCK": "0"}),
        ("no_late_skim",           {**TUNED_ENTRY, "SMART_EXIT_LATE_SKIM": "0"}),
        ("no_thesis_break",        {**TUNED_ENTRY, "SMART_EXIT_THESIS_BREAK": "0"}),
        ("no_late_salvage",        {**TUNED_ENTRY, "SMART_EXIT_LATE_SALVAGE": "0"}),
        ("only_skim+thesis",       {**TUNED_ENTRY, "SMART_EXIT_PROFIT_LOCK": "0", "SMART_EXIT_LATE_SALVAGE": "0"}),
    ], TARGET_BUNDLES)

    best_exit = max(p1, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 1 winner: {best_exit['label']}")

    base_ov = dict(best_exit['overrides'])

    # ---- PHASE 2: Exit parameter sweeps (on winner) ----
    p2 = phase("2 · Exit parameter sweeps", [
        ("exit_base",              dict(base_ov)),
        ("plock_arm=0.05",         {**base_ov, "SMART_PROFIT_LOCK_ARM": "0.05"}),
        ("plock_arm=0.15",         {**base_ov, "SMART_PROFIT_LOCK_ARM": "0.15"}),
        ("plock_gap=0.03",         {**base_ov, "SMART_PROFIT_LOCK_GAP": "0.03"}),
        ("plock_gap=0.08",         {**base_ov, "SMART_PROFIT_LOCK_GAP": "0.08"}),
        ("thesis_btc=0.001",       {**base_ov, "SMART_THESIS_BREAK_BTC": "0.001"}),
        ("thesis_btc=0.003",       {**base_ov, "SMART_THESIS_BREAK_BTC": "0.003"}),
        ("thesis_secs=90",         {**base_ov, "SMART_THESIS_BREAK_SECS": "90"}),
        ("thesis_secs=120",        {**base_ov, "SMART_THESIS_BREAK_SECS": "120"}),
        ("skim_bid=0.85",          {**base_ov, "SMART_LATE_SKIM_BID": "0.85"}),
        ("skim_bid=0.92",          {**base_ov, "SMART_LATE_SKIM_BID": "0.92"}),
    ], TARGET_BUNDLES)
    best_exit_params = max(p2, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 2 winner: {best_exit_params['label']}")
    base_ov = dict(best_exit_params['overrides'])

    # ---- PHASE 3: Binance staleness gate ----
    p3 = phase("3 · Binance staleness gate", [
        ("binance_off (base)",     dict(base_ov)),
        ("binance_age<=2s",        {**base_ov, "SMART_BINANCE_MAX_AGE": "2"}),
        ("binance_age<=3s",        {**base_ov, "SMART_BINANCE_MAX_AGE": "3"}),
        ("binance_age<=5s",        {**base_ov, "SMART_BINANCE_MAX_AGE": "5"}),
    ], TARGET_BUNDLES)
    best_p3 = max(p3, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 3 winner: {best_p3['label']}")
    base_ov = dict(best_p3['overrides'])

    # ---- PHASE 4: Time-in-bar min elapsed ----
    p4 = phase("4 · Min-elapsed entry gate", [
        ("no_min_elapsed (base)",  dict(base_ov)),
        ("min_elapsed=15",         {**base_ov, "SMART_MIN_ELAPSED_SECS": "15"}),
        ("min_elapsed=30",         {**base_ov, "SMART_MIN_ELAPSED_SECS": "30"}),
        ("min_elapsed=45",         {**base_ov, "SMART_MIN_ELAPSED_SECS": "45"}),
        ("min_elapsed=60",         {**base_ov, "SMART_MIN_ELAPSED_SECS": "60"}),
    ], TARGET_BUNDLES)
    best_p4 = max(p4, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 4 winner: {best_p4['label']}")
    base_ov = dict(best_p4['overrides'])

    # ---- PHASE 5: Volatility regime (sigma cap) ----
    p5 = phase("5 · Sigma cap", [
        ("no_sigma_cap (base)",    dict(base_ov)),
        ("sigma<=0.002",           {**base_ov, "SMART_MAX_SIGMA": "0.002"}),
        ("sigma<=0.003",           {**base_ov, "SMART_MAX_SIGMA": "0.003"}),
        ("sigma<=0.004",           {**base_ov, "SMART_MAX_SIGMA": "0.004"}),
        ("sigma<=0.005",           {**base_ov, "SMART_MAX_SIGMA": "0.005"}),
    ], TARGET_BUNDLES)
    best_p5 = max(p5, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 5 winner: {best_p5['label']}")
    base_ov = dict(best_p5['overrides'])

    # ---- PHASE 7: Shrinkage ----
    p7 = phase("7 · Shrinkage factor", [
        ("shrink=0.92 (base)",     dict(base_ov)),
        ("shrink=0.80",            {**base_ov, "SMART_SHRINKAGE": "0.80"}),
        ("shrink=0.85",            {**base_ov, "SMART_SHRINKAGE": "0.85"}),
        ("shrink=0.97",            {**base_ov, "SMART_SHRINKAGE": "0.97"}),
        ("shrink=1.00",            {**base_ov, "SMART_SHRINKAGE": "1.00"}),
    ], TARGET_BUNDLES)
    best_p7 = max(p7, key=lambda r: r['agg']['pnl'])
    print(f"\n>>> Phase 7 winner: {best_p7['label']}")
    base_ov = dict(best_p7['overrides'])

    # ---- PHASE 6: Sizing predictive check (detail) ----
    print("\n" + "=" * 72)
    print("PHASE 6 · Sizing predictive diagnostic")
    print("=" * 72)
    for b in TARGET_BUNDLES:
        r = run_one(b, base_ov, detail=True)
        if 'trades' not in r: continue
        bins = {1: [], 2: [], 3: []}
        for t in r['trades']:
            s = t['shares']
            if s <= 6: bins[1].append(t['pnl'])
            elif s <= 9: bins[2].append(t['pnl'])
            else: bins[3].append(t['pnl'])
        print(f"  {b.name}:")
        for lvl, pnls in bins.items():
            if pnls:
                print(f"    size_lvl={lvl}  n={len(pnls):3d}  pnl={sum(pnls):+7.2f}  avg={sum(pnls)/len(pnls):+.2f}")

    # ---- PHASE 8: Direction asymmetry diagnostic ----
    print("\n" + "=" * 72)
    print("PHASE 8 · Direction asymmetry (all bundles)")
    print("=" * 72)
    up_pnl = up_n = up_w = 0
    dn_pnl = dn_n = dn_w = 0
    for b in ALL_BUNDLES:
        r = run_one(b, base_ov, detail=True)
        if 'trades' not in r: continue
        for t in r['trades']:
            if t['direction'] == 'UP':
                up_pnl += t['pnl']; up_n += 1
                if t['pnl'] > 0: up_w += 1
            else:
                dn_pnl += t['pnl']; dn_n += 1
                if t['pnl'] > 0: dn_w += 1
    print(f"  UP   n={up_n:3d} pnl={up_pnl:+7.2f} avg={up_pnl/max(1,up_n):+.3f} wr={up_w/max(1,up_n):.2%}")
    print(f"  DOWN n={dn_n:3d} pnl={dn_pnl:+7.2f} avg={dn_pnl/max(1,dn_n):+.3f} wr={dn_w/max(1,dn_n):.2%}")

    # ---- PHASE 9: Final all-bundle validation ----
    print("\n" + "=" * 72)
    print("PHASE 9 · Final stacked config on ALL bundles")
    print("=" * 72)
    final_base_on_all = run_on("stack_on_ALL", base_ov, ALL_BUNDLES)
    original_on_all = run_on("original_on_ALL", {}, ALL_BUNDLES)  # pure YAML baseline
    print("\n--- Final comparison ---")
    print(f"  original      pnl=${original_on_all['agg']['pnl']:+.2f}  n={original_on_all['agg']['n']}  wr={original_on_all['agg']['wr']:.2%}")
    print(f"  stacked new   pnl=${final_base_on_all['agg']['pnl']:+.2f}  n={final_base_on_all['agg']['n']}  wr={final_base_on_all['agg']['wr']:.2%}")
    print("\nWinning overrides:")
    for k, v in sorted(base_ov.items()):
        print(f"  {k} = {v}")


if __name__ == "__main__":
    main()
