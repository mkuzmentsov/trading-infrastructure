#!/usr/bin/env bash
# Destroy an HL leaderboard CronJob.
# Usage: ./destroy.sh <name> [--yes]
set -euo pipefail

NAMESPACE="util"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <name> [--yes]"
  echo ""
  echo "Running releases:"
  helm list -n "$NAMESPACE" 2>/dev/null | tail -n +2 | awk '{print "  "$1}' || echo "  (none)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
SKIP_CONFIRM="${2:-}"

if [[ "$SKIP_CONFIRM" != "--yes" ]]; then
  read -r -p "Delete release '$RELEASE' from namespace '$NAMESPACE'? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

helm uninstall "$RELEASE" --namespace "$NAMESPACE"
echo "✓ Removed '$RELEASE'."
