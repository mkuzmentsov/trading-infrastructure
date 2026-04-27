#!/usr/bin/env bash
# Apply the model ConfigMap directly via kubectl, OUTSIDE the Helm release.
#
# Why: shipping the model files inside the chart makes the Helm release
# Secret exceed the 1 MiB Kubernetes limit. The deployment.yaml still
# references the ConfigMap by name; it just doesn't own its lifecycle.
#
# Usage: ./apply-model-configmap.sh <release-name>
# Example: ./apply-model-configmap.sh pm-btc-smart
set -euo pipefail

NAMESPACE="${NAMESPACE:-polymarket}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/files/model"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <release-name>"
  echo "  Example: $0 pm-btc-smart"
  exit 1
fi

RELEASE="$1"
CM_NAME="${RELEASE}-model"

if [[ ! -d "$MODEL_DIR" ]] || ! ls "$MODEL_DIR"/* &>/dev/null; then
  echo "Error: no model files in $MODEL_DIR"
  exit 1
fi

FROM_FILE_ARGS=()
for f in "$MODEL_DIR"/*; do
  FROM_FILE_ARGS+=("--from-file=$(basename "$f")=$f")
done

echo "▶ Applying ConfigMap '$CM_NAME' to namespace '$NAMESPACE' from $MODEL_DIR ..."
ls "$MODEL_DIR" | sed 's/^/    /'
# Use server-side apply: client-side apply stores the prior manifest in
# the kubectl.kubernetes.io/last-applied-configuration annotation, which
# has a 256 KiB cap — the model file alone is larger than that.
# --force-conflicts is needed because kubectl create previously created
# the ConfigMap with field manager "kubectl-create"; server-side apply
# claims those fields under "kubectl-client-side-apply".
kubectl create configmap "$CM_NAME" \
  --namespace "$NAMESPACE" \
  "${FROM_FILE_ARGS[@]}" \
  --dry-run=client -o yaml \
  | kubectl apply --server-side --force-conflicts -f -

echo "✓ Done."
