#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 copy_hl_ls_1"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"

echo "Uninstalling release '$RELEASE' from namespace freqtrade ..."
helm uninstall "$RELEASE" --namespace freqtrade

echo "Done. Note: PVCs are not removed automatically."
echo "  To delete PVCs: kubectl delete pvc -l app.kubernetes.io/instance=$RELEASE --namespace freqtrade"
