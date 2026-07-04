#!/usr/bin/env python3
"""(Re)generate the expected-metrics baseline for one date's dataset.
Usage: python3 tests/gen_baseline.py <YYYY-MM-DD>
Only run deliberately — the integration test exists to catch UNINTENDED changes."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
import sim

date = sys.argv[1]
d = os.path.join(HERE, "data", date)
bars = sim.load_events(d)
klines = json.load(sim._open(os.path.join(d, "klines_5m.json.gz")))
regimes = sim.classify_regimes(klines)
expected = {
    "metrics": sim.metrics(bars),
    "salvage_90_020_020": sim.sim_salvage(bars, 90, 0.20, 0.20),
    "grid_head": sim.grid_q(bars, regimes, prices=(0.48,))[:6],
}
json.dump(expected, open(os.path.join(d, "expected_metrics.json"), "w"), indent=1, sort_keys=True)
print(date, json.dumps(expected["metrics"]))
