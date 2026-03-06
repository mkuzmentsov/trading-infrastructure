#!/usr/bin/env bash
# Deploy a single Hummingbot arbitrage bot instance.
# Usage: ./deploy.sh <name>
# Example: ./deploy.sh hl_wb_arb_1
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 hl_wb_arb_1"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES="$SCRIPT_DIR/bots/${NAME}.yaml"
CHART="$SCRIPT_DIR/hummingbot-arb"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  echo "Create it from the example: cp bots/hl_wb_arb_1.yaml.example bots/${NAME}.yaml"
  exit 1
fi

echo "Deploying release '$RELEASE' from $VALUES ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace hummingbot --create-namespace

echo "Done."
echo "  Logs:   kubectl logs -f deploy/$RELEASE -n hummingbot"
echo "  Status: helm list -n hummingbot"
