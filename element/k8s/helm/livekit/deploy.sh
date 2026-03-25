#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/chart"
VALUES="$SCRIPT_DIR/values.instance.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  echo "  cp $SCRIPT_DIR/values.instance.example.yaml $VALUES"
  echo "  Then fill in externalIp, apiKey, apiSecret, and ingress.host."
  exit 1
fi

echo "Deploying LiveKit SFU server..."
helm upgrade --install livekit "$CHART" \
  -f "$VALUES" \
  --namespace element --create-namespace

echo "Done."
echo ""
echo "Check status:  kubectl rollout status deploy/livekit -n element"
echo "Logs:          kubectl logs -f deploy/livekit -n element"
