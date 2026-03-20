#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/chart"
VALUES="$SCRIPT_DIR/values.instance.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  echo "  cp $SCRIPT_DIR/values.instance.example.yaml $VALUES"
  echo "  Then fill in externalIp, sharedSecret, and realm."
  exit 1
fi

echo "Deploying Coturn TURN server..."
helm upgrade --install coturn "$CHART" \
  -f "$VALUES" \
  --namespace element --create-namespace

echo "Done."
echo ""
echo "Check status:  kubectl rollout status deploy/coturn -n element"
echo "Logs:          kubectl logs -f deploy/coturn -n element"
