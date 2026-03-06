#!/usr/bin/env bash
# Uninstall Loki + Grafana stack.
set -euo pipefail

NAMESPACE="monitoring"
RELEASE="loki-stack"

echo "Uninstalling $RELEASE from namespace '$NAMESPACE'..."
helm uninstall "$RELEASE" --namespace "$NAMESPACE"

echo "Done."
echo "Note: PVCs (log storage) are NOT removed automatically."
echo "  To delete: kubectl delete pvc -l app=loki -n $NAMESPACE"
