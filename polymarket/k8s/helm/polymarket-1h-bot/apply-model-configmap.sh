#!/usr/bin/env bash
# Apply the model ConfigMap directly via kubectl, OUTSIDE the Helm release.
#
# Why: shipping the model files inside the chart makes the Helm release
# Secret exceed the 1 MiB Kubernetes limit. The deployment.yaml still
# references the ConfigMap by name; it just doesn't own its lifecycle.
#
# Files larger than ~900 KiB are gzipped into the ConfigMap (with a `.gz`
# suffix). exit_gate_ml.py decompresses transparently at load.
#
# Usage: ./apply-model-configmap.sh <release-name>
# Example: ./apply-model-configmap.sh pm-btc-1h-smart
set -euo pipefail

NAMESPACE="${NAMESPACE:-polymarket}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/files/model"
# Files at or above this size get gzipped before going into the ConfigMap.
# K8s ConfigMaps cap at 1 MiB; leave headroom for other files in the CM.
GZIP_THRESHOLD_BYTES=921600  # 900 KiB

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <release-name>"
  echo "  Example: $0 pm-btc-1h-smart"
  exit 1
fi

RELEASE="$1"
CM_NAME="${RELEASE}-model"

if [[ ! -d "$MODEL_DIR" ]] || ! ls "$MODEL_DIR"/* &>/dev/null; then
  echo "Error: no model files in $MODEL_DIR"
  exit 1
fi

# Stage files into a tempdir, gzipping anything over the threshold.
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

FROM_FILE_ARGS=()
for f in "$MODEL_DIR"/*; do
  base="$(basename "$f")"
  size=$(wc -c < "$f")
  if (( size >= GZIP_THRESHOLD_BYTES )); then
    gzip -c "$f" > "$STAGE_DIR/${base}.gz"
    new_size=$(wc -c < "$STAGE_DIR/${base}.gz")
    printf '    %-44s  %7d B → gz %7d B\n' "$base" "$size" "$new_size"
    FROM_FILE_ARGS+=("--from-file=${base}.gz=$STAGE_DIR/${base}.gz")
  else
    cp "$f" "$STAGE_DIR/$base"
    printf '    %-44s  %7d B\n' "$base" "$size"
    FROM_FILE_ARGS+=("--from-file=${base}=$STAGE_DIR/$base")
  fi
done

echo "▶ Applying ConfigMap '$CM_NAME' to namespace '$NAMESPACE' from $MODEL_DIR ..."
# Use server-side apply: client-side apply stores the prior manifest in
# the kubectl.kubernetes.io/last-applied-configuration annotation, which
# has a 256 KiB cap.
# --force-conflicts is needed because kubectl create previously created
# the ConfigMap with field manager "kubectl-create"; server-side apply
# claims those fields under "kubectl-client-side-apply".
kubectl create configmap "$CM_NAME" \
  --namespace "$NAMESPACE" \
  "${FROM_FILE_ARGS[@]}" \
  --dry-run=client -o yaml \
  | kubectl apply --server-side --force-conflicts -f -

echo "✓ Done."
