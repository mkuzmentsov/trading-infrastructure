#!/bin/zsh
# archive_mrec — drain, then convert the VENUE tapes (brec/hrec) to zstd
# parquet and prune the raw files that converted cleanly.
#
# Order matters: drain first (pods -> local, verified), then convert local raw
# -> parquet, then prune ONLY files whose parquet was written and read back
# with a matching row count. Same verify-then-delete discipline as the drain.
#
# The Polymarket tapes (mrec/mrecev) are NOT touched here — they have their own
# richer pipeline in winner-vacuum/tools/mrec/ (snap2pq/ev2pq/panel/...), which
# is run on demand for research.
#
# Usage: archive_mrec.sh [--no-prune]
set -u
ROOT=/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra
MREC=$ROOT/every-tick-single/data/mrec
PQ=$ROOT/every-tick-single/data/pq-venue
PRUNE="--prune"
[ "${1:-}" = "--no-prune" ] && PRUNE=""

cd $ROOT || exit 1
$ROOT/every-tick-single/tools/drain_mrec.sh 2>&1 | grep -E "^FAIL|^DRAINED" | \
  awk '/DRAINED/{d++} /FAIL/{f++; print} END{printf "drain: %d ok, %d failed\n", d+0, f+0}'

# convert everything EXCEPT the current UTC hour (still being written)
TODAY=$(date -u +%Y%m%d)
python3 $ROOT/winner-vacuum/tools/mrec/venue2pq.py "$MREC" "$PQ" $PRUNE 2>&1 | tail -12
echo "pq-venue: $(du -sh $PQ 2>/dev/null | cut -f1)  raw-left: $(du -sh $MREC 2>/dev/null | cut -f1)"
