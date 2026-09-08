Agent A (2026-09-07, maker hunt round 3). Run from a dir with `pq` -> the mrec v2 parquet build,
`lad10.parquet` -> the 10-level ladder build, and the parent `tickjump/*.py` harness on the path.
`tick_raw.jsonl` = `zgrep tick_size_change` over every `<coin>-mrecev-*.jsonl.gz` (a12 parses it).
Order: a2 (fills) -> a3/a7/a8/a10 -> a12 -> a13/a14.  Write-up: docs/strat-maker-hunt-r3-20260907.md.
