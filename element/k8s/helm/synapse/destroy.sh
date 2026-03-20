#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling Synapse from namespace element..."
helm uninstall synapse --namespace element

echo "Done. Note: PVC is not removed automatically (signing key and DB are preserved)."
echo "  To fully wipe data: kubectl delete pvc synapse-pvc --namespace element"
