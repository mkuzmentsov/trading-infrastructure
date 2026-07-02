#!/usr/bin/env python3
"""Stack winning hypotheses from sweep_math_smart.py and validate on hold-out bundles."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep_math_smart import run_config, TARGET_BUNDLES, VALIDATION_BUNDLES, SCRIPT_DIR


def main():
    # Combos (greedy stack based on single-param sweep ranking)
    combos = [
        ("C0_baseline",                      {}),
        ("C1_floor035",                      {"SMART_ENTRY_FLOOR": "0.35"}),
        ("C2_late_ovr_tight",                {"SMART_LATE_FLOOR": "0.20", "SMART_LATE_OVERRIDE_Z": "3.0"}),
        ("C3_floor035 + late_ovr_tight",     {"SMART_ENTRY_FLOOR": "0.35",
                                              "SMART_LATE_FLOOR": "0.20",
                                              "SMART_LATE_OVERRIDE_Z": "3.0"}),
        ("C4_C3 + z_early=2.0",              {"SMART_ENTRY_FLOOR": "0.35",
                                              "SMART_LATE_FLOOR": "0.20",
                                              "SMART_LATE_OVERRIDE_Z": "3.0",
                                              "SMART_MIN_Z_EARLY": "2.0"}),
        ("C5_C3 + z_late=1.2",               {"SMART_ENTRY_FLOOR": "0.35",
                                              "SMART_LATE_FLOOR": "0.20",
                                              "SMART_LATE_OVERRIDE_Z": "3.0",
                                              "SMART_MIN_Z_LATE": "1.2"}),
        ("C6_C3 + late_ovr_off",             {"SMART_ENTRY_FLOOR": "0.35",
                                              "SMART_LATE_FLOOR": "0.35",
                                              "SMART_LATE_CEIL": "0.70"}),
        ("C7_C4 + z_late=1.2",               {"SMART_ENTRY_FLOOR": "0.35",
                                              "SMART_LATE_FLOOR": "0.20",
                                              "SMART_LATE_OVERRIDE_Z": "3.0",
                                              "SMART_MIN_Z_EARLY": "2.0",
                                              "SMART_MIN_Z_LATE": "1.2"}),
        ("C8_floor040",                      {"SMART_ENTRY_FLOOR": "0.40"}),
        ("C9_C3 + floor040",                 {"SMART_ENTRY_FLOOR": "0.40",
                                              "SMART_LATE_FLOOR": "0.20",
                                              "SMART_LATE_OVERRIDE_Z": "3.0"}),
    ]

    print("=" * 70)
    print("PHASE A: Combos on TARGET bundles")
    print("=" * 70)

    results_target = []
    for label, ov in combos:
        r = run_config(label, ov, TARGET_BUNDLES)
        results_target.append(r)

    print("\n" + "=" * 70)
    print("Ranked on TARGET:")
    print("=" * 70)
    for r in sorted(results_target, key=lambda r: r["agg"]["pnl"], reverse=True):
        a = r["agg"]
        print(f"  {a['label']:35s} pnl=${a['pnl']:+7.2f}  n={a['n']:3d}  wr={a['wr']:.2%}")

    print("\n" + "=" * 70)
    print("PHASE B: Top 5 on VALIDATION bundles (no regression check)")
    print("=" * 70)

    top = sorted(results_target, key=lambda r: r["agg"]["pnl"], reverse=True)[:5]
    all_bundles = TARGET_BUNDLES + VALIDATION_BUNDLES

    final = []
    for r in top:
        label = r["label"] + "_ALL"
        res = run_config(label, r["overrides"], all_bundles)
        final.append((r, res))

    print("\n" + "=" * 70)
    print("FINAL: target + validation combined")
    print("=" * 70)
    print(f"{'label':35s} {'target':>10s} {'val':>10s} {'combined':>10s} {'n':>5s} {'wr':>6s}")
    for r_target, r_all in final:
        tgt = r_target["agg"]["pnl"]
        combined = r_all["agg"]["pnl"]
        val = round(combined - tgt, 2)
        print(f"  {r_target['label']:33s} ${tgt:+7.2f}  ${val:+7.2f}  ${combined:+7.2f}  {r_all['agg']['n']:3d}  {r_all['agg']['wr']:.2%}")


if __name__ == "__main__":
    main()
