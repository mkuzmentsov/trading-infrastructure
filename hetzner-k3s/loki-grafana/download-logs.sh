#!/usr/bin/env bash
# Download logs from Loki (running in K8s) to a local file.
# Uses kubectl port-forward + logcli to batch-fetch without hitting query limits.
set -euo pipefail

NAMESPACE="monitoring"
LOKI_SVC="loki-stack"
LOKI_PORT="3100"
LOKI_ADDR="http://localhost:$LOKI_PORT"

# Defaults (override via env or args)
LOG_NAMESPACE="${LOG_NAMESPACE:-hummingbot}"
SINCE="${SINCE:-}"          # UTC timestamp, e.g. "2026-04-13T22:00:00Z" or "2026-04-13 22:00:00"
HOURS="${HOURS:-24}"        # fallback if SINCE not provided
LIMIT="${LIMIT:-100000}"
BATCH="${BATCH:-1000}"
OUTPUT="${OUTPUT:-logs_$(date +%Y%m%d_%H%M%S).txt}"
EXTRA_FILTER="${EXTRA_FILTER:-}"  # e.g. '|= "ERROR"'

usage() {
  echo "Usage: [LOG_NAMESPACE=...] [SINCE='2026-04-13T22:00:00Z'] [HOURS=24] [LIMIT=100000] [OUTPUT=logs.txt] [EXTRA_FILTER='|= \"ERROR\"'] $0"
  echo ""
  echo "Examples:"
  echo "  $0                                                  # last 24h"
  echo "  SINCE='2026-04-13T22:00:00Z' $0                    # from UTC timestamp"
  echo "  SINCE='2026-04-13 22:00:00' OUTPUT=run.txt $0      # space separator also works"
  echo "  HOURS=48 OUTPUT=my-logs.txt $0"
  echo "  LOG_NAMESPACE=freqtrade EXTRA_FILTER='|= \"ERROR\"' $0"
  exit 1
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

# Check dependencies
for cmd in kubectl logcli; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: '$cmd' not found. Install with: brew install $cmd"
    exit 1
  fi
done

if [[ -n "$SINCE" ]]; then
  # Normalise: replace space separator with T and ensure Z suffix
  SINCE_NORM="${SINCE/ /T}"
  [[ "$SINCE_NORM" != *Z ]] && SINCE_NORM="${SINCE_NORM}Z"
  FROM="$SINCE_NORM"
  RANGE_LABEL="since $FROM"
else
  FROM=$(date -v-${HOURS}H -u +%Y-%m-%dT%H:%M:%SZ)
  RANGE_LABEL="last ${HOURS}h"
fi

TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
QUERY="{namespace=\"$LOG_NAMESPACE\"}${EXTRA_FILTER:+ $EXTRA_FILTER}"

echo "==> Loki log downloader"
echo "    Namespace : $LOG_NAMESPACE"
echo "    Range     : $FROM → $TO ($RANGE_LABEL)"
echo "    Query     : $QUERY"
echo "    Output    : $OUTPUT"
echo ""

# Start port-forward in background
echo "==> Starting port-forward to $LOKI_SVC:$LOKI_PORT..."
kubectl port-forward "svc/$LOKI_SVC" "$LOKI_PORT:$LOKI_PORT" -n "$NAMESPACE" &>/dev/null &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null; echo '==> Port-forward closed.'" EXIT

# Wait for port to be ready
for i in {1..10}; do
  if curl -s "$LOKI_ADDR/ready" | grep -q "ready"; then
    break
  fi
  sleep 1
done

echo "==> Downloading logs..."
logcli query "$QUERY" \
  --addr="$LOKI_ADDR" \
  --from="$FROM" \
  --to="$TO" \
  --limit="$LIMIT" \
  --batch="$BATCH" \
  --forward \
  --output=raw \
  > "$OUTPUT"

LINES=$(wc -l < "$OUTPUT" | tr -d ' ')
echo "==> Done. $LINES lines saved to $OUTPUT"