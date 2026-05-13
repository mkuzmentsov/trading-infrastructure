#!/usr/bin/env bash
# Uninstall a funding-carry bot release.
# Usage: ./destroy.sh <name>
#
# WARNING: this only removes the K8s objects. If the bot held a real position
# you must flatten it MANUALLY first (or let the bot run with dry_run=false
# after a `close_pair` action). Uninstalling a deployed pod abandons its
# in-flight orders/positions.
set -euo pipefail

NAMESPACE="funding-carry"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"

read -r -p "Uninstall release '$RELEASE' in ns '$NAMESPACE'? Did you flatten positions? [type 'yes']: " ans
if [[ "$ans" != "yes" ]]; then
  echo "Aborted."
  exit 1
fi

helm uninstall "$RELEASE" --namespace "$NAMESPACE"
echo ""
echo "Helm release removed. The state PVC ($RELEASE-state) is NOT deleted automatically."
echo "To also remove state:"
echo "  kubectl delete pvc $RELEASE-state -n $NAMESPACE"
