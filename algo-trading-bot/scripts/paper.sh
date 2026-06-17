#!/usr/bin/env bash
# Build and run the paper trader. Fetches data first if ./data is empty.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "$(ls -A data/bars 2>/dev/null || true)" ]; then
  echo "No data found — fetching first..."
  ./scripts/fetch.sh
fi

echo "Starting paper trader (Ctrl-C to stop; state persists in ./state)..."
docker compose up --build paper
