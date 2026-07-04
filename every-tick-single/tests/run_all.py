#!/usr/bin/env python3
"""Run the full test suite (unit + integration) in isolated processes —
config.py freezes env at import, so each module gets a clean interpreter."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
suites = [
    os.path.join(HERE, "unit", "test_paper_book.py"),
    os.path.join(HERE, "unit", "test_strategy_rules.py"),
    os.path.join(HERE, "unit", "test_rotation.py"),
    os.path.join(HERE, "unit", "test_live_book.py"),
    os.path.join(HERE, "test_backtest_integration.py"),
]
fail = 0
for s in suites:
    r = subprocess.run([sys.executable, s], capture_output=True, text=True,
                       cwd=os.path.join(HERE, ".."))
    ok = r.returncode == 0
    print(("PASS " if ok else "FAIL ") + os.path.relpath(s, HERE))
    if not ok:
        fail += 1
        print(r.stdout[-1500:], r.stderr[-1500:])
sys.exit(1 if fail else 0)
