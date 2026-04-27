#!/usr/bin/env bash
# Fetch logs for pm-btc pods since they were started:
#   - Loki logs (via kubectl port-forward + logcli) -> loki.log
#   - /app/logs/logs-training.jsonl
#   - /app/logs/logs-training-events.jsonl
#
# Usage:
#   ./fetch-logs.sh              # fetch both bots
#   ./fetch-logs.sh 1            # fetch pm-btc-1 only
#   ./fetch-logs.sh 2            # fetch pm-btc-2 only
set -euo pipefail

# --- Config ---------------------------------------------------------------
NAMESPACE="${NAMESPACE:-polymarket}"
BOT_NUM="${1:-}"                              # 1, 2, or empty for both
LOKI_NS="${LOKI_NS:-monitoring}"
LOKI_SVC="${LOKI_SVC:-loki-stack}"
LOKI_PORT="${LOKI_PORT:-3100}"
LOKI_ADDR="http://localhost:$LOKI_PORT"
LIMIT="${LIMIT:-5000000}"
BATCH="${BATCH:-5000}"
# Cap the loki query to the most recent N hours regardless of pod uptime —
# avoids hitting LIMIT on long-running pods (the cap returns *oldest* lines
# first with --forward, so the trade window gets dropped). Override to 0 to
# use full pod uptime.
LOKI_HOURS="${LOKI_HOURS:-12}"

# --- Dependencies ---------------------------------------------------------
for cmd in kubectl logcli date; do
  command -v "$cmd" &>/dev/null || { echo "Error: '$cmd' not found"; exit 1; }
done

# --- Build pod list -------------------------------------------------------
if [[ -n "$BOT_NUM" ]]; then
  SELECTORS=("pm-btc-$BOT_NUM")
else
  SELECTORS=("pm-btc-1" "pm-btc-2")
fi

# --- Start Loki port-forward once -----------------------------------------
echo "==> Port-forwarding $LOKI_SVC:$LOKI_PORT ..."
kubectl -n "$LOKI_NS" port-forward "svc/$LOKI_SVC" "$LOKI_PORT:$LOKI_PORT" &>/dev/null &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true" EXIT

for i in {1..15}; do
  curl -s "$LOKI_ADDR/ready" 2>/dev/null | grep -q "ready" && break
  sleep 1
done

# --- Fetch each bot -------------------------------------------------------
for SELECTOR in "${SELECTORS[@]}"; do
  POD_NAME=$(kubectl -n "$NAMESPACE" get pods -o name \
    | grep "$SELECTOR" | head -n1 | sed 's|pod/||')

  if [[ -z "$POD_NAME" ]]; then
    echo "Warning: no pod matching '$SELECTOR' in ns '$NAMESPACE', skipping"
    continue
  fi

  OUT_DIR="./pm-btc-logs_${SELECTOR}_$(date +%Y%m%d_%H%M%S)"

  START_TIME=$(kubectl -n "$NAMESPACE" get pod "$POD_NAME" \
    -o jsonpath='{.status.startTime}')
  [[ -z "$START_TIME" ]] && { echo "Error: could not read startTime for $POD_NAME"; continue; }

  TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$OUT_DIR"

  echo ""
  echo "============================================================"
  echo "==> Bot       : $SELECTOR"
  echo "==> Pod       : $NAMESPACE/$POD_NAME"
  echo "==> Started   : $START_TIME"
  echo "==> Now (UTC) : $TO"
  echo "==> Output    : $OUT_DIR"
  echo "============================================================"

  # --- Copy JSONL training logs from container ---------------------------
  # Why not `kubectl exec ... cat`: the SPDY stream silently truncates large
  # outputs (~10MB+ depending on cluster load). Confirmed truncation on
  # bundle 20260427_101449 at exactly 7.67MB mid-line.
  # Why not `kubectl cp`: requires `tar` in the container; the bot image is
  # python:3.11-slim which has no tar.
  # Solution: stream through base64 (text-only, multiplexer-safe). The file
  # is appended ~2/sec so the snapshot we copy is always slightly stale by
  # design — that's fine. Trim any trailing partial line so downstream JSON
  # parsers don't choke on a half-record at EOF.
  echo "==> Copying /app/logs/*.jsonl from pod..."
  copy_remote_file() {
    local pod="$1"
    local remote_path="$2"
    local local_path="$3"
    if ! kubectl -n "$NAMESPACE" exec "$pod" -- \
         sh -c "base64 -w0 '$remote_path'" 2>/dev/null \
         | base64 -d > "$local_path"; then
      return 1
    fi
    # Trim a trailing partial line if present (last byte != '\n').
    local last_byte
    last_byte=$(tail -c1 "$local_path" 2>/dev/null | od -An -c | tr -d ' ')
    if [[ "$last_byte" != '\n' ]]; then
      python3 - "$local_path" <<'PY'
import sys
p = sys.argv[1]
with open(p, "rb") as f: data = f.read()
nl = data.rfind(b"\n")
if nl >= 0:
    with open(p, "wb") as f: f.write(data[: nl + 1])
PY
    fi
    return 0
  }
  for f in logs-training.jsonl logs-training-events.jsonl; do
    if kubectl -n "$NAMESPACE" exec "$POD_NAME" -- test -f "/app/logs/$f" 2>/dev/null; then
      if copy_remote_file "$POD_NAME" "/app/logs/$f" "$OUT_DIR/$f"; then
        echo "    ok: $f"
      else
        echo "    warn: failed copying $f"
      fi
    else
      echo "    skip: /app/logs/$f not present"
    fi
  done

  # --- Loki logs ---------------------------------------------------------
  # Split into hour-sized chunks — most Loki deployments have a server-side
  # max_entries_limit_per_query (often ~35K) that quietly truncates the
  # response regardless of --limit. A single full-pod query stops at the cap;
  # hourly chunks keep each query under it. LOKI_HOURS=0 means full pod uptime.
  QUERY="{namespace=\"$NAMESPACE\", pod=\"$POD_NAME\"}"
  if [[ "$LOKI_HOURS" -gt 0 ]]; then
    if date -u -v-1H +%Y-%m-%dT%H:%M:%SZ &>/dev/null; then
      LOKI_FROM=$(date -u -v-${LOKI_HOURS}H +%Y-%m-%dT%H:%M:%SZ)
    else
      LOKI_FROM=$(date -u -d "${LOKI_HOURS} hours ago" +%Y-%m-%dT%H:%M:%SZ)
    fi
    if [[ "$LOKI_FROM" < "$START_TIME" ]]; then
      LOKI_FROM="$START_TIME"
    fi
  else
    LOKI_FROM="$START_TIME"
  fi
  echo "==> Loki query: $QUERY"
  echo "==> Range     : $LOKI_FROM -> $TO  (pod started $START_TIME)"

  iso_to_epoch() {
    if date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s &>/dev/null; then
      date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$1" +%s
    else
      date -u -d "$1" +%s
    fi
  }
  epoch_to_iso() {
    if date -j -u -r "$1" +%Y-%m-%dT%H:%M:%SZ &>/dev/null; then
      date -j -u -r "$1" +%Y-%m-%dT%H:%M:%SZ
    else
      date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ
    fi
  }
  CHUNK=3600
  FROM_EP=$(iso_to_epoch "$LOKI_FROM")
  TO_EP=$(iso_to_epoch "$TO")
  : > "$OUT_DIR/loki.log"
  cur=$FROM_EP
  while [[ "$cur" -lt "$TO_EP" ]]; do
    nxt=$(( cur + CHUNK ))
    [[ "$nxt" -gt "$TO_EP" ]] && nxt="$TO_EP"
    chunk_from=$(epoch_to_iso "$cur")
    chunk_to=$(epoch_to_iso "$nxt")
    logcli query "$QUERY" \
      --addr="$LOKI_ADDR" \
      --from="$chunk_from" \
      --to="$chunk_to" \
      --limit="$LIMIT" \
      --batch="$BATCH" \
      --forward \
      --output=raw \
      --quiet \
      >> "$OUT_DIR/loki.log" 2>/dev/null || true
    cur="$nxt"
  done

  LINES=$(wc -l < "$OUT_DIR/loki.log" | tr -d ' ')
  echo "==> Done. Loki lines: $LINES"
  echo ""
  echo "Artifacts in $OUT_DIR:"
  ls -lh "$OUT_DIR"
done
