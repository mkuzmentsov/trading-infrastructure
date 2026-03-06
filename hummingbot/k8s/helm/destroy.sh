#!/usr/bin/env bash
# Uninstall a Hummingbot arbitrage bot instance.
# Usage: ./destroy.sh <name>
# Example: ./destroy.sh hl_wb_arb_1
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 hl_wb_arb_1"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"

echo "Uninstalling release '$RELEASE' from namespace hummingbot ..."
helm uninstall "$RELEASE" --namespace hummingbot

echo "Done."
echo "Note: PVCs are NOT removed automatically."
echo "  To delete: kubectl delete pvc -l app.kubernetes.io/instance=$RELEASE -n hummingbot"
