#!/usr/bin/env bash
# Fetch logs for a pm-btc pod since it was started:
#   - Loki logs (via kubectl port-forward + logcli) -> loki.log
#   - /app/logs/logs-training.jsonl
#   - /app/logs/logs-training-events.jsonl
set -euo pipefail

# --- Config ---------------------------------------------------------------
NAMESPACE="${NAMESPACE:-polymarket}"
POD_SELECTOR="${POD_SELECTOR:-pm-btc}"     # substring match on pod name
POD_NAME="${POD_NAME:-}"                    # override: exact pod name
OUT_DIR="${OUT_DIR:-./pm-btc-logs_$(date +%Y%m%d_%H%M%S)}"

# Loki
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

# --- Resolve pod ----------------------------------------------------------
if [[ -z "$POD_NAME" ]]; then
  POD_NAME=$(kubectl -n "$NAMESPACE" get pods -o name \
    | grep "$POD_SELECTOR" | head -n1 | sed 's|pod/||')
fi
[[ -z "$POD_NAME" ]] && { echo "Error: no pod matching '$POD_SELECTOR' in ns '$NAMESPACE'"; exit 1; }

START_TIME=$(kubectl -n "$NAMESPACE" get pod "$POD_NAME" \
  -o jsonpath='{.status.startTime}')
[[ -z "$START_TIME" ]] && { echo "Error: could not read startTime for $POD_NAME"; exit 1; }

TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$OUT_DIR"

echo "==> Pod       : $NAMESPACE/$POD_NAME"
echo "==> Started   : $START_TIME"
echo "==> Now (UTC) : $TO"
echo "==> Output    : $OUT_DIR"
echo ""

# --- Copy JSONL training logs from container -----------------------------
echo "==> Copying /app/logs/*.jsonl from pod..."
for f in logs-training.jsonl logs-training-events.jsonl; do
  if kubectl -n "$NAMESPACE" exec "$POD_NAME" -- test -f "/app/logs/$f" 2>/dev/null; then
    kubectl -n "$NAMESPACE" cp "$POD_NAME:/app/logs/$f" "$OUT_DIR/$f" \
      && echo "    ok: $f" \
      || echo "    warn: failed copying $f"
  else
    echo "    skip: /app/logs/$f not present"
  fi
done

# --- Loki logs via port-forward ------------------------------------------
echo "==> Port-forwarding $LOKI_SVC:$LOKI_PORT ..."
kubectl -n "$LOKI_NS" port-forward "svc/$LOKI_SVC" "$LOKI_PORT:$LOKI_PORT" &>/dev/null &
PF_PID=$!
trap "kill $PF_PID 2>/dev/null || true" EXIT

for i in {1..15}; do
  curl -s "$LOKI_ADDR/ready" 2>/dev/null | grep -q "ready" && break
  sleep 1
done

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