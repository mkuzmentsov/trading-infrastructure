#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling lk-jwt-service from namespace element..."
helm uninstall lk-jwt-service --namespace element

echo "Done."
