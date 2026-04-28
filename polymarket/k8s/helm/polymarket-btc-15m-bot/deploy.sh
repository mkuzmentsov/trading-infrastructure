#!/usr/bin/env bash
# Deploy the Polymarket BTC 15m bot.
# Usage: ./deploy.sh <name>
# Example: ./deploy.sh pm_btc_15m_smart
#
# Looks up credentials/overrides at ../bots/<name>.yaml.
# Release name is derived from <name> by replacing _ with -.
set -euo pipefail

NAMESPACE="polymarket"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELM_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHART="$SCRIPT_DIR"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 pm_btc_15m_smart"
  echo ""
  echo "Available bot values files in ../bots/:"
  ls "$HELM_DIR/bots/"pm_btc_15m*.yaml 2>/dev/null | xargs -n1 basename | sed 's/\.yaml$//' | sed 's/^/  /' || echo "  (none — create $HELM_DIR/bots/<name>.yaml with bot.* and credentials.*)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
VALUES="$HELM_DIR/bots/${NAME}.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  exit 1
fi

echo "▶ Deploying '$RELEASE' (chart: polymarket-btc-15m-bot, namespace: $NAMESPACE) ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace "$NAMESPACE" --create-namespace

echo ""
echo "✓ Done."
echo ""
echo "  Logs:    kubectl logs -f deploy/$RELEASE -n $NAMESPACE"
echo "  Status:  helm list -n $NAMESPACE"
