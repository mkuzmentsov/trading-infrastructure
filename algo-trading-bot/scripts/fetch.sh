#!/usr/bin/env bash
# Fetch market data into ./data (one-shot, via the `tools` compose profile).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose --profile tools run --rm fetch "$@"
echo "Data in ./data/bars/"
