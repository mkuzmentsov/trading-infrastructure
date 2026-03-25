#!/usr/bin/env bash
# Deploy a Polymarket BTC bot instance.
# Usage: ./deploy-btc.sh <name>
# Example: ./deploy-btc.sh pm_btc_1
set -euo pipefail

NAMESPACE="polymarket"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/polymarket-btc-bot"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 pm_btc_1"
  echo ""
  echo "Available bots:"
  ls "$SCRIPT_DIR/bots/"pm_btc*.yaml 2>/dev/null | xargs -n1 basename | sed 's/\.yaml$//' | sed 's/^/  /' || echo "  (none — copy pm_btc_1.yaml.example to pm_btc_1.yaml and fill in credentials)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
VALUES="$SCRIPT_DIR/bots/${NAME}.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  echo "Tip: cp $SCRIPT_DIR/bots/pm_btc_1.yaml.example $VALUES  and fill in credentials"
  exit 1
fi

echo "▶ Deploying '$RELEASE' (namespace: $NAMESPACE) ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace "$NAMESPACE" --create-namespace

echo ""
echo "✓ Done."
echo ""
echo "  Logs:    kubectl logs -f deploy/$RELEASE -n $NAMESPACE"
echo "  Status:  helm list -n $NAMESPACE"
echo ""
echo "  ⚠ IMPORTANT: Copy your trained model to the pod's PVC:"
echo "    POD=\$(kubectl get pod -n $NAMESPACE -l app.kubernetes.io/instance=$RELEASE -o name | head -1)"
echo "    kubectl cp ai/model_target_dir_5m_*.txt \$POD:/app/data/model.txt -n $NAMESPACE"
