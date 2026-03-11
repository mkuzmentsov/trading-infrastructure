#!/usr/bin/env bash
# Destroy a Polymarket Claude bot instance.
# Usage: ./destroy.sh <name> [--yes]
# Example: ./destroy.sh pm_claude_1
set -euo pipefail

NAMESPACE="polymarket"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <name> [--yes]"
  echo "  Example: $0 pm_claude_1"
  echo ""
  echo "Running releases:"
  helm list -n "$NAMESPACE" 2>/dev/null | tail -n +2 | awk '{print "  "$1}' || echo "  (none)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
SKIP_CONFIRM="${2:-}"

if [[ "$SKIP_CONFIRM" != "--yes" ]]; then
  echo "This will delete Helm release '$RELEASE' in namespace '$NAMESPACE'."
  echo "The PVC (positions data) will NOT be deleted automatically."
  read -r -p "Continue? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

echo "▶ Uninstalling '$RELEASE' ..."
helm uninstall "$RELEASE" --namespace "$NAMESPACE"

echo ""
echo "✓ Done. Release '$RELEASE' removed."
echo ""
echo "  To also delete the positions PVC:"
echo "    kubectl delete pvc $RELEASE-pvc -n $NAMESPACE"
echo ""
echo "  To delete the entire namespace (removes ALL bots and PVCs):"
echo "    kubectl delete namespace $NAMESPACE"
