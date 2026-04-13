#!/usr/bin/env bash
# Copy training log files from a running bot pod to the local working directory.
# Pod name is resolved dynamically via label selector.
set -euo pipefail

# Defaults (override via env)
POD_NAMESPACE="${POD_NAMESPACE:-polymarket}"
POD_LABEL="${POD_LABEL:-app.kubernetes.io/name=polymarket-btc-bot}"
REMOTE_DIR="${REMOTE_DIR:-/app/logs}"
OUTPUT_DIR="${OUTPUT_DIR:-.}"

FILES=(
  "logs-training.jsonl"
  "logs-training-events.jsonl"
)

usage() {
  echo "Usage: [POD_NAMESPACE=polymarket] [POD_LABEL=app=pm-btc-1] [OUTPUT_DIR=.] $0"
  echo ""
  echo "Examples:"
  echo "  $0"
  echo "  POD_LABEL=${POD_LABEL} OUTPUT_DIR=./run-data $0"
  exit 1
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

# Resolve pod name
POD=$(kubectl get pod -n "$POD_NAMESPACE" -l "$POD_LABEL" \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [[ -z "$POD" ]]; then
  echo "Error: no running pod found in namespace '$POD_NAMESPACE' with label '$POD_LABEL'"
  exit 1
fi

echo "==> Pod: $POD"
echo "    Namespace: $POD_NAMESPACE"
echo "    Remote dir: $REMOTE_DIR"
echo "    Output dir: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

for FILE in "${FILES[@]}"; do
  SRC="$POD_NAMESPACE/$POD:$REMOTE_DIR/$FILE"
  DST="$OUTPUT_DIR/$FILE"
  echo "==> Copying $FILE ..."
  kubectl cp "$SRC" "$DST"
  LINES=$(wc -l < "$DST" | tr -d ' ')
  echo "    Saved $LINES lines → $DST"
done

echo ""
echo "==> Done."
