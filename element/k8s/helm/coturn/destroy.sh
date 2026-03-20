#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling Coturn from namespace element..."
helm uninstall coturn --namespace element

echo "Done."
