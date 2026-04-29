#!/usr/bin/env python3
"""Follow-up sweep: profit_lock arm tuning (with exit ON), and size_max_mult cap."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep_big import run_on, phase, TARGET_BUNDLES, ALL_BUNDLES, TUNED_ENTRY

# Baseline = tuned entry + skim@0.85 (winner so far, no_profit_lock).
base = {**TUNED_ENTRY, "SMART_LATE_SKIM_BID": "0.85"}

# -- profit_lock tuning with it ON --
p_lock = phase("Profit-lock tuning (ENABLED, sweep arm/gap)", [
    ("plock_OFF (best so far)", {**base, "SMART_EXIT_PROFIT_LOCK": "0"}),
    ("plock_default_0.10/0.05", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.10", "SMART_PROFIT_LOCK_GAP": "0.05"}),
    ("plock_arm=0.15_gap=0.05", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.15", "SMART_PROFIT_LOCK_GAP": "0.05"}),
    ("plock_arm=0.20_gap=0.05", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.20", "SMART_PROFIT_LOCK_GAP": "0.05"}),
    ("plock_arm=0.25_gap=0.08", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.25", "SMART_PROFIT_LOCK_GAP": "0.08"}),
    ("plock_arm=0.30_gap=0.10", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.30", "SMART_PROFIT_LOCK_GAP": "0.10"}),
    ("plock_arm=0.10_gap=0.10", {**base, "SMART_EXIT_PROFIT_LOCK": "1",
                                 "SMART_PROFIT_LOCK_ARM": "0.10", "SMART_PROFIT_LOCK_GAP": "0.10"}),
], TARGET_BUNDLES)

best_lock = max(p_lock, key=lambda r: r['agg']['pnl'])
print(f"\n>>> Profit-lock winner: {best_lock['label']}")

base2 = dict(best_lock['overrides'])

# -- size mult cap sweep (phase 6 showed size_lvl=3 negative) --
p_size = phase("Size multiplier cap", [
    ("size_max=2.0 (base)",    dict(base2)),
    ("size_max=1.5",           {**base2, "SMART_SIZE_MAX_MULT": "1.5"}),
    ("size_max=1.25",          {**base2, "SMART_SIZE_MAX_MULT": "1.25"}),
    ("size_max=1.0 (flat)",    {**base2, "SMART_SIZE_MAX_MULT": "1.0"}),
    ("size_min=1.0 (boost small)", {**base2, "SMART_SIZE_MIN_MULT": "1.0"}),
    ("size_flat_1.0 (1.0,1.0)",{**base2, "SMART_SIZE_MIN_MULT": "1.0", "SMART_SIZE_MAX_MULT": "1.0"}),
], TARGET_BUNDLES)
best_size = max(p_size, key=lambda r: r['agg']['pnl'])
print(f"\n>>> Size winner: {best_size['label']}")

# -- final all-bundle validation with ultimate stack --
base3 = dict(best_size['overrides'])
print("\n" + "=" * 72)
print("FINAL all-bundle validation")
print("=" * 72)
final = run_on("ultimate_stack", base3, ALL_BUNDLES)
only_entry = run_on("entry_only_tune", TUNED_ENTRY, ALL_BUNDLES)
baseline = run_on("yaml_baseline", {}, ALL_BUNDLES)

print("\n--- Ranked on ALL bundles ---")
for r in sorted([final, only_entry, baseline], key=lambda r: r['agg']['pnl'], reverse=True):
    a = r['agg']
    print(f"  {a['label']:25s} pnl=${a['pnl']:+7.2f} n={a['n']:3d} wr={a['wr']:.2%}")

print("\nUltimate stack overrides:")
for k, v in sorted(base3.items()):
    print(f"  {k} = {v}")
