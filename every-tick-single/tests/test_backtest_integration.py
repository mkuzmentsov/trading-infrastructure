#!/usr/bin/env python3
"""Integration tests: the backtest pipeline over FROZEN per-date datasets.

tests/data/<YYYY-MM-DD>/ holds one day's real bot data (+ klines) and its
expected_metrics.json baseline. The test discovers every date present locally
and asserts (1) pipeline integrity and (2) exact baseline reproduction.

If a sim change alters a baseline: inspect, and if the change is a deliberate
improvement (per EXPERIMENTS.md decision rules), regenerate via
tests/gen_baseline.py <date> and justify in the commit. Never regenerate to
silence a failure. Fetch missing dates: tests/fetch_day.py <date>.

Run: python3 tests/test_backtest_integration.py   (or pytest)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
import sim  # noqa: E402

DATA = os.path.join(HERE, "data")


def dates():
    return sorted(d for d in os.listdir(DATA)
                  if os.path.isdir(os.path.join(DATA, d))
                  and os.path.exists(os.path.join(DATA, d, "expected_metrics.json")))


def load(date):
    d = os.path.join(DATA, date)
    bars = sim.load_events(d)
    klines = json.load(sim._open(os.path.join(d, "klines_5m.json.gz")))
    return bars, sim.classify_regimes(klines)


def check_integrity(date, bars, regimes):
    assert len(bars) > 100, f"[{date}] fixture parse regressed: {len(bars)} bars"
    assert sum(1 for b in bars.values() if b["outcome"]) > 100, f"[{date}] outcomes missing"
    assert sum(1 for b in bars.values() if b["positions"]) > 50, f"[{date}] settle<->snapshot join broke"
    assert any(regimes.get((c, b["bar_ts"])) for (c, _), b in bars.items()), f"[{date}] regime join broke"


def check_baseline(date, bars, regimes):
    expected = json.load(open(os.path.join(DATA, date, "expected_metrics.json")))
    got = {
        "metrics": sim.metrics(bars),
        "salvage_90_020_020": sim.sim_salvage(bars, 90, 0.20, 0.20),
        "grid_head": sim.grid_q(bars, regimes, prices=(0.48,))[:6],
    }
    for key, exp in expected.items():
        assert got[key] == exp, f"[{date}] {key} changed:\n got {got[key]}\n exp {exp}"


def test_all_dates():
    ds = dates()
    assert ds, "no date datasets found under tests/data/"
    for date in ds:
        bars, regimes = load(date)
        check_integrity(date, bars, regimes)
        check_baseline(date, bars, regimes)


if __name__ == "__main__":
    for date in dates():
        bars, regimes = load(date)
        check_integrity(date, bars, regimes)
        check_baseline(date, bars, regimes)
        print(f"OK {date} — integrity + baseline hold")
