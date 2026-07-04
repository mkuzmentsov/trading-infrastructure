#!/usr/bin/env python3
"""Characterization test: midnight event-log rotation (gzip + prune)."""
import gzip
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

os.environ.setdefault("QUOTE_MODE", "bracket")
os.environ.setdefault("PAPER_MODE", "true")
os.environ["LOG_ROTATE_KEEP_DAYS"] = "2"

import main  # noqa: E402


class FakeTime:
    """Stand-in for main.time — controls the rotation day."""

    def __init__(self, day):
        self.day = day

    def strftime(self, fmt, t=None):
        return self.day

    def gmtime(self):
        return None

    def time(self):
        return 0.0


def test_rotation_gzips_prunes_and_restarts():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ev.jsonl")
    real_time = main.time
    try:
        main.time = FakeTime("2026-07-01")
        main._last_rotate_day = "2026-07-01"
        main._append_jsonl(path, {"d": 1}, "t")
        # midnight: day flips → old content gzipped, live file restarts
        main.time = FakeTime("2026-07-02")
        main._append_jsonl(path, {"d": 2}, "t")
        assert os.path.exists(f"{path}.2026-07-01.gz")
        assert json.loads(gzip.open(f"{path}.2026-07-01.gz").read()) == {"d": 1}
        assert json.loads(open(path).read()) == {"d": 2}
        # two more days → keep=2 prunes the oldest archive
        main.time = FakeTime("2026-07-03")
        main._append_jsonl(path, {"d": 3}, "t")
        main.time = FakeTime("2026-07-04")
        main._append_jsonl(path, {"d": 4}, "t")
        archives = sorted(f for f in os.listdir(tmp) if f.endswith(".gz"))
        assert archives == ["ev.jsonl.2026-07-02.gz", "ev.jsonl.2026-07-03.gz"], archives
    finally:
        main.time = real_time


def test_no_rotation_same_day():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ev.jsonl")
    real_time = main.time
    try:
        main.time = FakeTime("2026-07-05")
        main._last_rotate_day = "2026-07-05"
        main._append_jsonl(path, {"a": 1}, "t")
        main._append_jsonl(path, {"a": 2}, "t")
        assert len(open(path).read().splitlines()) == 2
        assert not [f for f in os.listdir(tmp) if f.endswith(".gz")]
    finally:
        main.time = real_time


if __name__ == "__main__":
    test_rotation_gzips_prunes_and_restarts()
    print("OK test_rotation_gzips_prunes_and_restarts")
    test_no_rotation_same_day()
    print("OK test_no_rotation_same_day")
