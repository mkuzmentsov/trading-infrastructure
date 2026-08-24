#!/bin/bash
# openmm deploy. ./deploy.sh <coin> <paper|live>
# Own program, own Polymarket account, own chart — shares only the commons
# (src/{config.py,core,engine} -> every-tick-single/src, src/execution -> pm-common).
# source ../.dev-env-source first (Hetzner k3s, ns every-tick-single).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
COIN="${1:?coin}"; MODE="${2:-paper}"
# openmm runs on its OWN account (signer 0xD17E…FD0a / vault 0xd632c1e1…),
# deliberately NOT the vacmaker fleet's (0x7BbDaf… / 0xdB66d896…), so this
# pilot's PnL and maker rebates are independently measurable and a bug here
# cannot reach the working fleet.
CREDS="${BOT_CREDS:-$ROOT/every-tick-single/chart/bots/openmm.secret.yaml}"
cd "$HERE"
CTX=$(kubectl config current-context)
if [[ "$CTX" != "hetzner-k3s-cluster-master1" ]]; then
  echo "ERROR: kube context is '$CTX', expected hetzner-k3s-cluster-master1." >&2
  echo "Run: cd <repo root> && source .dev-env-source" >&2
  exit 1
fi
rsync -aL --delete src/ chart/files/scripts/ >/dev/null
find chart/files/scripts -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find chart/files/scripts -name '*.pyc' -delete 2>/dev/null || true
if [ "$MODE" = "live" ] && [ ! -f "$CREDS" ]; then
  echo "ERROR: credentials overlay not found: $CREDS" >&2
  echo "  cp $ROOT/every-tick-single/chart/bots/openmm.secret.yaml.example \\" >&2
  echo "     $CREDS   and fill it in (see the header for which address goes where)." >&2
  exit 1
fi
ARGS=(-f "chart/bots/${COIN}_openmm.yaml")
[ "$MODE" = "live" ] && { ARGS+=(-f "$CREDS"); echo ">>> LIVE ${COIN}-openmm (REAL MONEY)"; } || echo ">>> PAPER ${COIN}-openmm"
helm upgrade --install "${COIN}-openmm-every-tick-single" ./chart "${ARGS[@]}" -n every-tick-single
echo "done: ${COIN}-openmm-every-tick-single ($MODE)"
