#!/usr/bin/env bash
# Deploy a pattern-bot release.
# Usage: ./deploy.sh <name>
# Example: ./deploy.sh pb_btc_1
#
# Looks up overrides at bots/<name>.yaml. Release name = <name> with _ → -.
# Rsyncs ../../bot/*.py into the chart's files/bot/ so the ConfigMap always
# carries the canonical source (no drifting chart copy of the code).
set -euo pipefail

NAMESPACE="pattern-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART="$SCRIPT_DIR/pattern-bot"
BOT_SRC="$(cd "$SCRIPT_DIR/../../bot" && pwd)"
CHART_BOT_DIR="$CHART/files/bot"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo ""
  echo "Available bot overlays in bots/:"
  ls "$SCRIPT_DIR/bots/"*.yaml 2>/dev/null | xargs -n1 basename | sed 's/\.yaml$//' | sed 's/^/  /' \
    || echo "  (none — copy bots/pb_btc_1.yaml.example to bots/<name>.yaml and fill creds)"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
VALUES="$SCRIPT_DIR/bots/${NAME}.yaml"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: overlay not found: $VALUES"
  echo "Copy bots/pb_btc_1.yaml.example to bots/${NAME}.yaml and fill in credentials."
  exit 1
fi

echo "▶ Syncing bot code: $BOT_SRC → $CHART_BOT_DIR"
mkdir -p "$CHART_BOT_DIR"
# Only the runtime .py files. Config & state belong in K8s objects, not the image.
rsync -a --delete \
  --include='*.py' \
  --include='.gitkeep' \
  --exclude='*' \
  "$BOT_SRC/" "$CHART_BOT_DIR/"

echo "▶ Deploying release '$RELEASE' (chart: pattern-bot, namespace: $NAMESPACE)"
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace "$NAMESPACE" --create-namespace

echo ""
echo "✓ Done."
echo "  Logs:    kubectl logs -f deploy/$RELEASE -n $NAMESPACE"
echo "  Status:  helm list -n $NAMESPACE"
echo "  Shell:   kubectl exec -it deploy/$RELEASE -n $NAMESPACE -- /bin/bash"
