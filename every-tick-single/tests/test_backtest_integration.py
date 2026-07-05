#!/usr/bin/env python3
"""Integration tests: the backtest pipeline over FROZEN per-date datasets.

tests/data/<YYYY-MM-DD>/ holds one day's expected_metrics.json baseline (the
committed regression ledger). The bulk *.gz event dumps are committed ONLY for
the 2026-07-03 reference fixture (others are gitignored, ~20MB/day) — so on a
fresh checkout only 2026-07-03 runs fully; other dates are SKIPPED with a hint
until their data is fetched via tests/fetch_day.py <date>.

Discipline (encoded in ett-pull-events skill): whenever a NEW rotated event log
appears on the pods with no committed baseline yet, fetch that day
(tests/fetch_day.py) and add its baseline (tests/gen_baseline.py) so every
day the bots produced is a permanent regression check.

If a sim change alters a baseline: inspect, and if the change is a deliberate
improvement (per EXPERIMENTS.md decision rules), regenerate via
tests/gen_baseline.py <date> and justify in the commit. Never regenerate to
silence a failure.

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


def has_data(date):
    """True if this date's bulk .gz dumps are present locally (not just the baseline)."""
    d = os.path.join(DATA, date)
    return (os.path.exists(os.path.join(d, "klines_5m.json.gz"))
            and any(os.path.exists(os.path.join(d, f"{c}_snap.jsonl.gz")) for c in sim.COINS))


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
    assert ds, "no date baselines found under tests/data/"
    ran = 0
    for date in ds:
        if not has_data(date):
            continue  # baseline committed, bulk data not local — fetch to verify
        bars, regimes = load(date)
        check_integrity(date, bars, regimes)
        check_baseline(date, bars, regimes)
        ran += 1
    assert ran >= 1, "no date has local data to verify (expected the 2026-07-03 fixture)"


if __name__ == "__main__":
    for date in dates():
        if not has_data(date):
            print(f"SKIP {date} — baseline committed, data not local (tests/fetch_day.py {date} to verify)")
            continue
        bars, regimes = load(date)
        check_integrity(date, bars, regimes)
        check_baseline(date, bars, regimes)
        print(f"OK {date} — integrity + baseline hold")
