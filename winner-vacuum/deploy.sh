#!/bin/bash
# winner-vacuum deploy. ./deploy.sh <coin> <paper|live>
# Bundles src/ (deref symlinks → commons) into chart/files/scripts, helm upgrades.
# source ../.dev-env-source first (Hetzner k3s, ns every-tick-single).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; MODE="${2:-paper}"
CREDS="$ROOT/every-tick-single/chart/bots/pm.secret.yaml"
cd "$HERE"
rsync -aL --delete src/ chart/files/scripts/ >/dev/null
find chart/files/scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find chart/files/scripts -name '*.pyc' -delete 2>/dev/null || true
ARGS=(-f "chart/bots/${COIN}_vacuum.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE ${COIN}-vacuum (real money)"; } || echo ">>> PAPER ${COIN}-vacuum"
helm upgrade --install "${COIN}-vacuum-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-vacuum-every-tick-single ($MODE)"
