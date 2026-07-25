#!/bin/bash
# nextrev deploy. ./deploy.sh <coin> [paper|live]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; MODE="${2:-paper}"
CREDS="$ROOT/every-tick-single/chart/bots/sol.secret.yaml"
cd "$HERE"
rsync -aL --delete src/ chart/files/scripts/ >/dev/null
find chart/files/scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
rm -f chart/files/scripts/strategy/cur2_models.py
ARGS=(-f "chart/bots/${COIN}_nextrev.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE $COIN-nextrev"; } || echo ">>> PAPER $COIN-nextrev"
helm upgrade --install "${COIN}-nextrev-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-nextrev ($MODE)"
