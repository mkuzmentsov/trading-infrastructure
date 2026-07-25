#!/bin/bash
# settlement-sniper deploy. ./deploy.sh <coin> <snipe|flip> <paper|live>
# Bundles src/ (deref symlinks → commons) into chart/files/scripts, helm upgrades.
# source ../.dev-env-source first (Hetzner k3s, ns every-tick-single).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; STRAT="${2:?snipe|flip}"; MODE="${3:-paper}"
CREDS="$ROOT/every-tick-single/chart/bots/sol.secret.yaml"
cd "$HERE"
rsync -aL --delete src/ chart/files/scripts/ >/dev/null
find chart/files/scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find chart/files/scripts -name '*.pyc' -delete 2>/dev/null || true
ARGS=(-f "chart/bots/${COIN}_${STRAT}.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE $COIN-$STRAT (real money)"; } || echo ">>> PAPER $COIN-$STRAT"
helm upgrade --install "${COIN}-${STRAT}-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-${STRAT}-every-tick-single ($MODE)"
