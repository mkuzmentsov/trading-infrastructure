#!/bin/bash
# crash-catcher deploy. ./deploy.sh <coin> <paper|live>
# Bundles src/ (deref symlinks → commons) into chart/files/scripts, helm upgrades.
# source ../.dev-env-source first (Hetzner k3s, ns every-tick-single).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; MODE="${2:-paper}"
# Trading bots run on their OWN Polymarket account (crypto.secret.yaml).
# scout.secret.yaml is the pm-scout / world-bets account — do NOT point bots
# at it, or a key rotation on one side silently moves the other.
# Override with BOT_CREDS=/path/to/overlay.
CREDS="${BOT_CREDS:-$ROOT/every-tick-single/chart/bots/crypto.secret.yaml}"
cd "$HERE"
rsync -aL --delete src/ chart/files/scripts/ >/dev/null
find chart/files/scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find chart/files/scripts -name '*.pyc' -delete 2>/dev/null || true
if [ "$MODE" = "live" ] && [ ! -f "$CREDS" ]; then
  echo "ERROR: bot credentials not found: $CREDS" >&2
  echo "  Trading bots use their own Polymarket account. Create that overlay" >&2
  echo "  (see chart/bots/crypto.secret.yaml.example), or set BOT_CREDS=<path>." >&2
  echo "  scout.secret.yaml belongs to pm-scout - do not reuse it here." >&2
  exit 1
fi
ARGS=(-f "chart/bots/${COIN}_catcher.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE ${COIN}-catcher (real money)"; } || echo ">>> PAPER ${COIN}-catcher"
helm upgrade --install "${COIN}-catcher-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-catcher-every-tick-single ($MODE)"
