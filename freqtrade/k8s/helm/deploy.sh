#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <name>"
  echo "  Example: $0 copy_hl_ls_1"
  exit 1
fi

NAME="$1"
RELEASE="${NAME//_/-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES="$SCRIPT_DIR/bots/${NAME}.yaml"
CHART="$SCRIPT_DIR/freqtrade-bot"

if [[ ! -f "$VALUES" ]]; then
  echo "Error: values file not found: $VALUES"
  exit 1
fi

echo "Deploying release '$RELEASE' using $VALUES ..."
helm upgrade --install "$RELEASE" "$CHART" \
  -f "$VALUES" \
  --namespace freqtrade --create-namespace

echo "Done."
