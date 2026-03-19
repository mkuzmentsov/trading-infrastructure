#!/usr/bin/env bash
# Deploy an HL leaderboard CronJob.
# Usage: ./deploy.sh <name>
# Example: ./deploy.sh hl_leaderboard_1
set -euo pipefail

NAMESPACE="util"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/hl-leaderboard"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 hl_leaderboard_1"
  echo ""
  echo "Available jobs:"
  ls "$SCRIPT_DIR/jobs/"*.yaml 2>/dev/null | xargs -n1 basename | sed 's/\.yaml$//' | sed 's/^/  /' || echo "  (none)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
VALUES="$SCRIPT_DIR/jobs/${NAME}.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  exit 1
fi

# Embed the latest hl_leaderboard.py into the chart before deploying
echo "Copying hl_leaderboard.py into chart ..."
cp "$REPO_ROOT/util/hl_leaderboard.py" "$CHART/files/hl_leaderboard.py"

echo "▶ Deploying '$RELEASE' (namespace: $NAMESPACE) ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace "$NAMESPACE" --create-namespace

echo ""
echo "✓ Done."
echo ""
echo "  Trigger now: kubectl create job --from=cronjob/$RELEASE manual-$(date +%s) -n $NAMESPACE"
echo "  Logs:        kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=hl-leaderboard --tail=500"
echo "  Status:      helm list -n $NAMESPACE"
