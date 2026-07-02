#!/usr/bin/env python3
"""Random sweep over NEW knobs layered on current seed=42 joint-winner.

Tests: size_z_cap, directional_divergence, thesis_break_sigma_mult,
profit_lock_min_entry_price, profit_lock_min_abs_p, regime_align/against,
size_mode=kelly, ml_gate_min_p.

Baseline = current yaml (seed=42 winner). We only flip one or a small
combo of new knobs per config, compare to $88.62 target / $147.87 all-bundle.
"""
from __future__ import annotations
import json, os, random, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from sweep_math_smart import BASE_ENV  # noqa: E402

TARGET_BUNDLES = [
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260419_101700"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260420_075109"),
]
ALL_BUNDLES = TARGET_BUNDLES + [
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260418_224248"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_101755"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_155128"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_195918"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_224258"),
]

# Current winning YAML config (seed=42 joint-winner), in env form.
WINNER = {
    "SMART_MIN_Z_EARLY": "2.0",
    "SMART_MIN_Z_LATE": "1.2",
    "SMART_MIN_BOOK_DIVERGENCE": "0.02",
    "SMART_ENTRY_FLOOR": "0.30",
    "SMART_ENTRY_CEIL": "0.75",
    "SMART_LATE_FLOOR": "0.20",
    "SMART_LATE_CEIL": "0.85",
    "SMART_LATE_OVERRIDE_Z": "3.5",
    "SMART_SIZE_Z_REF": "1.5",
    "SMART_SIZE_MIN_MULT": "1.5",
    "SMART_SIZE_MAX_MULT": "2.0",
    "SMART_EXIT_PROFIT_LOCK": "0",
    "SMART_LATE_SKIM_BID": "0.85",
    "SMART_LATE_SKIM_SECS": "120",
    "SMART_SALVAGE_SECS": "60",
    "SMART_THESIS_BREAK_BTC": "0.0010",
}

CHILD = r"""
import json, os, sys
from pathlib import Path
scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts / 'files' / 'scripts'))
sys.path.insert(0, str(scripts / 'files' / 'scripts' / 'strategies'))
sys.path.insert(0, str(scripts))
from strategies.bundle_backtest import BundleBacktestRunner
cfg = {
    'STRATEGY_NAME': 'math_smart',
    'ENTRY_CONFIRMATION_TICKS': 1, 'ENTRY_MIN_SECONDS_LEFT': 20,
    'STOP_LOSS_MARKET_LIMIT': 1,
    'TRAILING_ARM_GAIN': 0.99, 'TRAILING_STOP_GAP': 0.05,
    'TAKE_PROFIT': 0.90, 'STOP_LOSS': 0.90,
    'SL_ARM_DELAY_SECS': 60, 'SL_MIN_ADVERSE_BTC': 0.0015,
    'ULTRA_CHEAP_SL_DELAY_SECS': 120,
}
out = {}
for b in sys.argv[2:]:
    r = BundleBacktestRunner(cfg=cfg).run_tick_strategy(b)
    w = sum(1 for t in r.trades if t.pnl > 0)
    out[Path(b).name] = {
        'n': len(r.trades),
        'pnl': round(sum(t.pnl for t in r.trades), 2),
        'w': w,
    }
print(json.dumps(out))
"""


def sample_knobs(rng: random.Random) -> dict[str, str]:
    """Sample NEW knob values. Keep most OFF so we isolate effects."""
    cfg = {}
    # Size z-cap
    if rng.random() < 0.3:
        cfg["SMART_SIZE_Z_CAP"] = f"{rng.choice([1.5, 2.0, 2.5, 3.0]):.2f}"
    # Directional divergence
    if rng.random() < 0.3:
        cfg["SMART_DIVERGENCE_DIRECTIONAL"] = "1"
    # Sigma-aware thesis
    if rng.random() < 0.3:
        cfg["SMART_THESIS_BREAK_SIGMA_MULT"] = f"{rng.choice([0.3, 0.5, 0.75, 1.0, 1.5]):.2f}"
    # Conditional profit-lock (requires EXIT_PROFIT_LOCK=1)
    if rng.random() < 0.35:
        cfg["SMART_EXIT_PROFIT_LOCK"] = "1"
        cfg["SMART_PROFIT_LOCK_ARM"] = f"{rng.choice([0.15, 0.20, 0.25, 0.30]):.2f}"
        cfg["SMART_PROFIT_LOCK_GAP"] = f"{rng.choice([0.05, 0.08, 0.10]):.2f}"
        if rng.random() < 0.6:
            cfg["SMART_PROFIT_LOCK_MIN_ENTRY_PRICE"] = f"{rng.choice([0.50, 0.60, 0.65, 0.70]):.2f}"
        if rng.random() < 0.4:
            cfg["SMART_PROFIT_LOCK_MIN_ABS_P"] = f"{rng.choice([0.10, 0.15, 0.20]):.2f}"
    # Regime-aware sizing
    if rng.random() < 0.25:
        cfg["SMART_REGIME_ALIGN"] = f"{rng.choice([1.1, 1.25, 1.5]):.2f}"
        cfg["SMART_REGIME_AGAINST"] = f"{rng.choice([0.5, 0.7, 0.85]):.2f}"
    # Kelly sizing
    if rng.random() < 0.2:
        cfg["SMART_SIZE_MODE"] = "kelly"
    # ML gate
    if rng.random() < 0.3:
        cfg["SMART_ML_GATE_MIN_P"] = f"{rng.choice([0.40, 0.45, 0.50, 0.55, 0.60]):.2f}"
    return cfg


def run_job(args):
    cid, cfg, bundles = args
    env = dict(os.environ)
    env.update(BASE_ENV)
    env.update(WINNER)  # baseline = winner
    env.update(cfg)     # overlay new knobs
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, str(SCRIPT_DIR), *bundles],
        env=env, capture_output=True, text=True, timeout=240,
    )
    if proc.returncode != 0:
        return cid, {"error": proc.stderr[-300:]}
    try:
        return cid, json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return cid, {"error": f"parse: {e}"}


def aggregate(per_bundle: dict) -> dict:
    n = sum(v.get("n", 0) for v in per_bundle.values() if "n" in v)
    pnl = sum(v.get("pnl", 0) for v in per_bundle.values() if "pnl" in v)
    w = sum(v.get("w", 0) for v in per_bundle.values() if "w" in v)
    return {"n": n, "pnl": round(pnl, 2), "wr": round(w / max(1, n), 3)}


def main():
    seed = int(os.environ.get("SWEEP_SEED", "101"))
    rng = random.Random(seed)
    N = int(os.environ.get("SWEEP_N", "200"))

    # Always include the pure-baseline as config 0 for reference.
    configs = [(0, {})]  # pure winner
    for i in range(1, N):
        configs.append((i, sample_knobs(rng)))

    print(f"seed={seed} N={N}. Baseline = seed=42 joint-winner config.")
    print(f"Running {N} configs × {len(TARGET_BUNDLES)} target bundles ...")
    t0 = time.time()
    results = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_job, (cid, cfg, TARGET_BUNDLES)): (cid, cfg) for cid, cfg in configs}
        done = 0
        for fut in as_completed(futs):
            cid, cfg = futs[fut]
            _, res = fut.result()
            results[cid] = (cfg, res)
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{N}  ({time.time()-t0:.0f}s)")

    ranked = []
    for cid, (cfg, res) in results.items():
        if "error" in res:
            continue
        agg = aggregate(res)
        ranked.append((cid, cfg, res, agg))
    ranked.sort(key=lambda x: x[3]["pnl"], reverse=True)

    # Reference: pure baseline config 0
    baseline_target = next((r for r in ranked if r[0] == 0), None)
    if baseline_target:
        print(f"\nBASELINE (pure winner) target=${baseline_target[3]['pnl']:+.2f}  n={baseline_target[3]['n']}")

    print(f"\nTop 15 on target bundles ({time.time()-t0:.0f}s):")
    for cid, cfg, res, agg in ranked[:15]:
        knobs = ", ".join(f"{k.replace('SMART_', '')}={v}" for k, v in sorted(cfg.items())) or "<pure>"
        print(f"  #{cid:3d}  pnl=${agg['pnl']:+7.2f}  n={agg['n']:3d}  wr={agg['wr']:.2%}  |  {knobs}")

    # Validate top-10 on all bundles
    top10 = ranked[:10]
    print(f"\nValidating top-10 on {len(ALL_BUNDLES)} bundles...")
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_job, (cid, cfg, ALL_BUNDLES)): (cid, cfg, t_agg)
                for cid, cfg, _, t_agg in top10}
        all_results = []
        for fut in as_completed(futs):
            cid, cfg, t_agg = futs[fut]
            _, res = fut.result()
            if "error" in res:
                continue
            all_agg = aggregate(res)
            all_results.append((cid, cfg, t_agg, all_agg, res))

    all_results.sort(key=lambda x: x[3]["pnl"], reverse=True)

    print("\n=== TOP by ALL-BUNDLE PnL ===")
    print(f"{'#':>3s} {'target':>8s} {'all':>8s} {'n_all':>5s} {'wr_all':>7s}  overrides")
    for cid, cfg, t_agg, a_agg, res in all_results:
        knobs = ", ".join(f"{k.replace('SMART_', '')}={v}" for k, v in sorted(cfg.items())) or "<pure>"
        print(f"  {cid:3d}  ${t_agg['pnl']:+7.2f}  ${a_agg['pnl']:+7.2f}  {a_agg['n']:4d}   {a_agg['wr']:.2%}  {knobs}")

    print("\n=== WINNER CONFIG ===")
    if not all_results:
        print("no valid results")
        return
    cid, cfg, t_agg, a_agg, res = all_results[0]
    print(f"#{cid}  target=${t_agg['pnl']:+.2f}  all=${a_agg['pnl']:+.2f}  n={a_agg['n']}  wr={a_agg['wr']:.2%}")
    print("Per-bundle:")
    for name, v in res.items():
        if "n" in v:
            print(f"  {name:55s} n={v['n']:3d} pnl={v['pnl']:+7.2f}")
    print("\nOverrides (vs pure seed=42 winner):")
    for k, v in sorted(cfg.items()):
        print(f"  {k} = {v}")


if __name__ == "__main__":
    main()
