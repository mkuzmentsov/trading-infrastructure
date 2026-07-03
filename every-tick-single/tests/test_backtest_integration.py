#!/usr/bin/env python3
"""Integration test: the backtest pipeline over a FROZEN dump of real bot data.

Guards two things:
1. The pipeline keeps working end-to-end (event parsing, snapshot<->settle join
   on condition_id, regime classification, both sims) against real-shaped data.
2. PERFORMANCE REGRESSION BASELINE: headline metrics on the frozen fixture must
   match tests/expected_metrics.json exactly. If a strategy/sim change ALTERS
   these numbers, that is a deliberate decision: inspect, and if the change is
   an improvement (per EXPERIMENTS.md decision rules), regenerate the baseline
   and say so in the commit. Never regenerate to silence a failure.

Fixture: real events from the 4 paper bots + Binance 5m klines, 2026-07-03
06:00-14:45 UTC (regime mix: morning chop, midday trend, afternoon chop).
Run: python3 tests/test_backtest_integration.py   (or pytest)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backtest"))
import sim  # noqa: E402

DATA = os.path.join(HERE, "data")


def load():
    bars = sim.load_events(DATA)
    klines = json.load(sim._open(os.path.join(DATA, "klines_5m.json.gz")))
    return bars, sim.classify_regimes(klines)


def test_pipeline_integrity():
    bars, regimes = load()
    assert len(bars) > 150, f"fixture parse regressed: {len(bars)} bars"
    settled = [b for b in bars.values() if b["outcome"]]
    assert len(settled) > 150
    with_pos = [b for b in bars.values() if b["positions"]]
    assert len(with_pos) > 80, "settle<->snapshot join broke (condition_id join)"
    assert any(regimes.get((c, b["bar_ts"])) for (c, _), b in bars.items()), "regime join broke"


def test_performance_baseline():
    bars, regimes = load()
    expected = json.load(open(os.path.join(HERE, "expected_metrics.json")))
    got_metrics = sim.metrics(bars)
    assert got_metrics == expected["metrics"], (
        f"headline metrics changed:\n got {got_metrics}\n exp {expected['metrics']}")
    got_salvage = sim.sim_salvage(bars, 90, 0.20, 0.20)
    assert got_salvage == expected["salvage_90_020_020"], (
        f"salvage sim changed:\n got {got_salvage}\n exp {expected['salvage_90_020_020']}")
    got_grid = sim.grid_q(bars, regimes, prices=(0.48,))[:6]
    assert got_grid == expected["grid_head"], (
        f"grid changed:\n got {got_grid}\n exp {expected['grid_head']}")


if __name__ == "__main__":
    test_pipeline_integrity()
    test_performance_baseline()
    print("OK — pipeline integrity + performance baseline hold")
