#!/usr/bin/env bash
# Fetch logs for pm-btc-* pods since they were started:
#   - Loki logs (via kubectl port-forward + logcli) -> loki.log
#   - /app/logs/logs-training.jsonl
#   - /app/logs/logs-training-events.jsonl
#
# Usage:
#   ./fetch-logs.sh                                   # fetch all pm-* deployments
#   ./fetch-logs.sh pm-btc-5m-smart                   # one selector
#   ./fetch-logs.sh pm-btc-1h-smart pm-eth-1h-smart   # multiple
#
# A selector is matched as a substring against pod names in the namespace.
set -euo pipefail

# --- Paths ----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# polymarket/k8s/helm/fetch-logs.sh -> polymarket/logs (gitignored)
LOG_BASE_DIR="${LOG_BASE_DIR:-$SCRIPT_DIR/../../logs}"

# --- Config ---------------------------------------------------------------
NAMESPACE="${NAMESPACE:-polymarket}"
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

# --- Build selector list --------------------------------------------------
if [[ $# -gt 0 ]]; then
  SELECTORS=("$@")
else
  mapfile -t SELECTORS < <(kubectl -n "$NAMESPACE" get deploy -o name 2>/dev/null \
    | sed 's|deployment.apps/||' | grep '^pm-' || true)
  if [[ ${#SELECTORS[@]} -eq 0 ]]; then
    echo "Error: no pm-* deployments in namespace '$NAMESPACE'."
    echo "Tip: pass selectors explicitly, e.g. $0 pm-btc-1h-smart pm-eth-1h-smart"
    exit 1
  fi
  echo "==> Auto-discovered: ${SELECTORS[*]}"
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

  case "$SELECTOR" in
    *-1h-*)  SUBDIR="1h"  ;;
    *-15m-*) SUBDIR="15m" ;;
    *)       SUBDIR="5m"  ;;
  esac
  # Coin = second dash-segment of selector (pm-<coin>-<duration>-smart -> <coin>).
  # Falls back to "misc" if the pattern doesn't match.
  COIN="$(echo "$SELECTOR" | awk -F- '{print ($2 == "" ? "misc" : $2)}')"

  START_TIME=$(kubectl -n "$NAMESPACE" get pod "$POD_NAME" \
    -o jsonpath='{.status.startTime}')
  [[ -z "$START_TIME" ]] && { echo "Error: could not read startTime for $POD_NAME"; continue; }

  TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  # Compute pod runtime in hours and format START_TIME for the dir name. Python
  # keeps this portable across macOS/Linux without juggling `date -d` vs `-j -f`.
  read -r START_STAMP RUNTIME_HOURS <<<"$(python3 -c "
import datetime
start = datetime.datetime.fromisoformat('$START_TIME'.replace('Z','+00:00'))
now = datetime.datetime.now(datetime.timezone.utc)
h = (now - start).total_seconds() / 3600
print(start.strftime('%Y%m%d_%H%M%S'), f'{h:.1f}'.rstrip('0').rstrip('.'))
")"

  OUT_DIR="$LOG_BASE_DIR/$SUBDIR/$COIN/pm-logs_${SELECTOR}_${START_STAMP}_${RUNTIME_HOURS}h"
  mkdir -p "$OUT_DIR"

  echo ""
  echo "============================================================"
  echo "==> Bot       : $SELECTOR"
  echo "==> Pod       : $NAMESPACE/$POD_NAME"
  echo "==> Started   : $START_TIME"
  echo "==> Now (UTC) : $TO"
  echo "==> Runtime   : ${RUNTIME_HOURS}h"
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
