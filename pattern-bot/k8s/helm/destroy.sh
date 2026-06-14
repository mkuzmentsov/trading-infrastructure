#!/usr/bin/env bash
# Uninstall a pattern-bot release.
# Usage: ./destroy.sh <name>
#
# WARNING: this only removes the K8s objects. If the bot held a real position
# you must flatten it MANUALLY first. Uninstalling a deployed pod abandons any
# in-flight position.
set -euo pipefail

NAMESPACE="pattern-bot"

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
echo "To also remove state:  kubectl delete pvc $RELEASE-state -n $NAMESPACE"
