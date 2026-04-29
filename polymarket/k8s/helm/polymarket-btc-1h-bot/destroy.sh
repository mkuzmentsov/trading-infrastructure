#!/usr/bin/env bash
# Destroy a Polymarket BTC 1h bot release.
# Usage: ./destroy.sh <name> [--yes]
# Example: ./destroy.sh pm_btc_15m_smart
set -euo pipefail

NAMESPACE="polymarket"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <name> [--yes]"
  echo "  Example: $0 pm_btc_15m_smart"
  echo ""
  echo "Running releases in $NAMESPACE:"
  helm list -n "$NAMESPACE" 2>/dev/null | tail -n +2 | awk '{print "  "$1}' || echo "  (none)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
SKIP_CONFIRM="${2:-}"

if [[ "$SKIP_CONFIRM" != "--yes" ]]; then
  echo "This will delete Helm release '$RELEASE' in namespace '$NAMESPACE'."
  read -r -p "Continue? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

echo "▶ Uninstalling '$RELEASE' ..."
helm uninstall "$RELEASE" --namespace "$NAMESPACE"

echo ""
echo "✓ Done. Release '$RELEASE' removed."
