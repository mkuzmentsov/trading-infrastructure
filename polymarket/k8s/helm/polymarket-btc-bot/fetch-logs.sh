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
LIMIT="${LIMIT:-500000}"
BATCH="${BATCH:-1000}"

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
  echo "==> Copying /app/logs/*.jsonl from pod..."
  copy_remote_file() {
    local pod="$1"
    local remote_path="$2"
    local local_path="$3"
    local tries=0
    local max_tries=3
    while [[ $tries -lt $max_tries ]]; do
      tries=$((tries + 1))
      if kubectl -n "$NAMESPACE" exec "$pod" -- sh -c "cat '$remote_path'" > "$local_path"; then
        return 0
      fi
      sleep 1
    done
    return 1
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
  QUERY="{namespace=\"$NAMESPACE\", pod=\"$POD_NAME\"}"
  echo "==> Loki query: $QUERY"
  echo "==> Range     : $START_TIME -> $TO"

  logcli query "$QUERY" \
    --addr="$LOKI_ADDR" \
    --from="$START_TIME" \
    --to="$TO" \
    --limit="$LIMIT" \
    --batch="$BATCH" \
    --forward \
    --output=raw \
    > "$OUT_DIR/loki.log"

  LINES=$(wc -l < "$OUT_DIR/loki.log" | tr -d ' ')
  echo "==> Done. Loki lines: $LINES"
  echo ""
  echo "Artifacts in $OUT_DIR:"
  ls -lh "$OUT_DIR"
done
