#!/usr/bin/env python3
"""Joint random search over entry+exit+sizing params.

Avoids greedy-sweep interaction blindspots. Run ~400 configs on target bundles,
rank, validate top-20 on all bundles, pick best by all-bundle PnL.
"""
from __future__ import annotations
import json, os, random, subprocess, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from sweep_math_smart import BASE_ENV

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


def sample_config(rng: random.Random) -> dict[str, str]:
    cfg = {}
    cfg["SMART_ENTRY_FLOOR"] = f"{rng.choice([0.25, 0.30, 0.33, 0.35, 0.38, 0.40]):.2f}"
    cfg["SMART_ENTRY_CEIL"] = f"{rng.choice([0.65, 0.70, 0.75]):.2f}"
    cfg["SMART_LATE_FLOOR"] = f"{rng.choice([0.15, 0.18, 0.20, 0.22, 0.25, 0.30]):.2f}"
    cfg["SMART_LATE_CEIL"] = f"{rng.choice([0.82, 0.85, 0.88, 0.92]):.2f}"
    cfg["SMART_LATE_OVERRIDE_Z"] = f"{rng.choice([2.3, 2.5, 2.8, 3.0, 3.3, 3.5]):.2f}"
    cfg["SMART_MIN_Z_EARLY"] = f"{rng.choice([1.5, 1.6, 1.8, 2.0, 2.2]):.2f}"
    cfg["SMART_MIN_Z_LATE"] = f"{rng.choice([0.6, 0.8, 1.0, 1.2]):.2f}"
    cfg["SMART_MIN_BOOK_DIVERGENCE"] = f"{rng.choice([0.02, 0.03, 0.04, 0.05]):.3f}"

    # Exit: decide whether profit_lock is on at all
    if rng.random() < 0.3:
        cfg["SMART_EXIT_PROFIT_LOCK"] = "0"
    else:
        cfg["SMART_EXIT_PROFIT_LOCK"] = "1"
        cfg["SMART_PROFIT_LOCK_ARM"] = f"{rng.choice([0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]):.2f}"
        cfg["SMART_PROFIT_LOCK_GAP"] = f"{rng.choice([0.03, 0.05, 0.08, 0.10, 0.12, 0.15]):.2f}"
    cfg["SMART_LATE_SKIM_BID"] = f"{rng.choice([0.82, 0.85, 0.88, 0.90, 0.92]):.2f}"
    cfg["SMART_LATE_SKIM_SECS"] = f"{rng.choice([60, 90, 120])}"
    cfg["SMART_THESIS_BREAK_BTC"] = f"{rng.choice([0.001, 0.0015, 0.002, 0.003]):.4f}"
    cfg["SMART_SALVAGE_SECS"] = f"{rng.choice([30, 45, 60, 90])}"

    # Sizing
    cfg["SMART_SIZE_MIN_MULT"] = f"{rng.choice([0.5, 0.75, 1.0, 1.25, 1.5]):.2f}"
    cfg["SMART_SIZE_MAX_MULT"] = f"{rng.choice([1.0, 1.25, 1.5, 1.75, 2.0]):.2f}"
    cfg["SMART_SIZE_Z_REF"] = f"{rng.choice([1.5, 2.0, 2.5]):.2f}"

    # Ensure min <= max
    if float(cfg["SMART_SIZE_MIN_MULT"]) > float(cfg["SMART_SIZE_MAX_MULT"]):
        cfg["SMART_SIZE_MIN_MULT"] = cfg["SMART_SIZE_MAX_MULT"]

    return cfg


def run_job(args):
    cid, cfg, bundles = args
    env = dict(os.environ); env.update(BASE_ENV); env.update(cfg)
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
    seed = int(os.environ.get("SWEEP_SEED", "42"))
    rng = random.Random(seed)
    print(f"seed={seed}")
    N = 400
    configs = [(i, sample_config(rng)) for i in range(N)]

    print(f"Running {N} random configs × {len(TARGET_BUNDLES)} target bundles ...")
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
            if done % 40 == 0:
                print(f"  {done}/{N}  ({time.time()-t0:.0f}s)")

    # Rank on target
    ranked = []
    for cid, (cfg, res) in results.items():
        if "error" in res:
            continue
        agg = aggregate(res)
        ranked.append((cid, cfg, res, agg))
    ranked.sort(key=lambda x: x[3]["pnl"], reverse=True)

    print(f"\nTop 20 on target bundles ({time.time()-t0:.0f}s):")
    for cid, cfg, res, agg in ranked[:20]:
        print(f"  #{cid:3d}  pnl=${agg['pnl']:+7.2f}  n={agg['n']:3d}  wr={agg['wr']:.2%}")

    # Validate top-20 on all bundles
    top20 = ranked[:20]
    print(f"\nValidating top-20 on {len(ALL_BUNDLES)} bundles...")
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(run_job, (cid, cfg, ALL_BUNDLES)): (cid, cfg, target_agg)
                for cid, cfg, _, target_agg in top20}
        all_results = []
        for fut in as_completed(futs):
            cid, cfg, target_agg = futs[fut]
            _, res = fut.result()
            if "error" in res: continue
            all_agg = aggregate(res)
            all_results.append((cid, cfg, target_agg, all_agg, res))

    # Rank by combined score: all-bundle PnL with target bundle guardrail
    all_results.sort(key=lambda x: x[3]["pnl"], reverse=True)

    print("\n=== TOP 10 by ALL-BUNDLE PnL ===")
    print(f"{'#':>3s} {'target':>8s} {'all':>8s} {'n_all':>5s} {'wr_all':>7s}")
    for cid, cfg, t_agg, a_agg, res in all_results[:10]:
        print(f"  {cid:3d}  ${t_agg['pnl']:+7.2f}  ${a_agg['pnl']:+7.2f}  {a_agg['n']:4d}   {a_agg['wr']:.2%}")

    print("\n=== WINNER CONFIG ===")
    winner = all_results[0]
    cid, cfg, t_agg, a_agg, res = winner
    print(f"#{cid}  target=${t_agg['pnl']:+.2f}  all=${a_agg['pnl']:+.2f}  n={a_agg['n']}  wr={a_agg['wr']:.2%}")
    print("Per-bundle:")
    for name, v in res.items():
        if "n" in v:
            print(f"  {name:55s} n={v['n']:3d} pnl={v['pnl']:+7.2f}")
    print("\nOverrides:")
    # Write only differences vs YAML base (show useful diff).
    for k, v in sorted(cfg.items()):
        base = BASE_ENV.get(k, "")
        marker = "*" if str(v) != str(base) else " "
        print(f"  {marker} {k} = {v}  (base={base})")

    # Also show top runner-ups
    print("\n=== TOP 3 CONFIGS (full) ===")
    for rank, (cid, cfg, t_agg, a_agg, res) in enumerate(all_results[:3], 1):
        print(f"\n--- #{rank} (id={cid}) target=${t_agg['pnl']:+.2f} all=${a_agg['pnl']:+.2f} ---")
        for k, v in sorted(cfg.items()):
            print(f"  {k}={v}")


if __name__ == "__main__":
    main()
