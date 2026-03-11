#!/usr/bin/env bash
# Deploy a Polymarket Claude bot instance.
# Usage: ./deploy.sh <name>
# Example: ./deploy.sh pm_claude_1
set -euo pipefail

NAMESPACE="polymarket"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/polymarket-bot"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 pm_claude_1"
  echo ""
  echo "Available bots:"
  ls "$SCRIPT_DIR/bots/"*.yaml 2>/dev/null | xargs -n1 basename | sed 's/\.yaml$//' | sed 's/^/  /'
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
VALUES="$SCRIPT_DIR/bots/${NAME}.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  exit 1
fi

echo "▶ Deploying '$RELEASE' (namespace: $NAMESPACE) ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace "$NAMESPACE" --create-namespace

echo ""
echo "✓ Done."
echo ""
echo "  Logs:      kubectl logs -f deploy/$RELEASE -n $NAMESPACE"
echo "  Positions: kubectl exec deploy/$RELEASE -n $NAMESPACE -- cat /app/data/positions.json"
echo "  Status:    helm list -n $NAMESPACE"
