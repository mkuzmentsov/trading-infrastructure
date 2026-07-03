#!/usr/bin/env python3
"""Walk-forward validation: train on held-out bundles, test on target.

If the sweep on held-out bundles produces a similar winning config and it
still performs well on the target bundles, we trust the strategy isn't
overfit to the target pair.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sweep_joint  # re-use run_job, sample_config, aggregate

SCRIPT_DIR = Path(__file__).resolve().parent

# SWAP: train on held-out btc-2 + btc-3 early bundles; test on the 2 originals.
TRAIN_BUNDLES = [
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260418_224248"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_101755"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-2_20260419_155128"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_195918"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260418_224258"),
]
TEST_BUNDLES = [
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260419_101700"),
    str(SCRIPT_DIR / "pm-btc-logs_pm-btc-3_20260420_075109"),
]

sweep_joint.TARGET_BUNDLES = TRAIN_BUNDLES
sweep_joint.ALL_BUNDLES = TRAIN_BUNDLES + TEST_BUNDLES

if __name__ == "__main__":
    sweep_joint.main()
