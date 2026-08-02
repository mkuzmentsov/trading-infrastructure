#!/bin/bash
# winner-vacuum deploy. ./deploy.sh <coin> <paper|live> [bot]
# bot defaults to "vacuum"; e.g. ./deploy.sh btc live pennymint uses
# chart/bots/btc_pennymint.yaml and release btc-pennymint-every-tick-single.
# Bundles src/ (deref symlinks → commons) into chart/files/scripts, helm upgrades.
# source ../.dev-env-source first (Hetzner k3s, ns every-tick-single).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; MODE="${2:-paper}"; BOT="${3:-vacuum}"
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
ARGS=(-f "chart/bots/${COIN}_${BOT}.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE ${COIN}-${BOT} (real money)"; } || echo ">>> PAPER ${COIN}-${BOT}"
helm upgrade --install "${COIN}-${BOT}-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-${BOT}-every-tick-single ($MODE)"
