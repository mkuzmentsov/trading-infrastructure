#!/usr/bin/env bash
# Flip ONE coin to LIVE trading (real orders). Usage: ./golive.sh btc
# Requires chart/bots/creds.secret.yaml (gitignored) and a funded Polymarket wallet.
# Only touches the named coin's release — the rest of the fleet keeps running paper.
set -euo pipefail
cd "$(dirname "$0")"

COIN="${1:?usage: ./golive.sh <coin>}"
CTX=$(kubectl config current-context)
if [[ "$CTX" != "hetzner-k3s-cluster-master1" ]]; then
  echo "ERROR: kube context is '$CTX', expected hetzner-k3s-cluster-master1." >&2
  echo "Run: cd <repo root> && source .dev-env-source" >&2
  exit 1
fi
[[ -f chart/bots/creds.secret.yaml ]] || { echo "ERROR: chart/bots/creds.secret.yaml missing" >&2; exit 1; }
[[ -f "chart/bots/${COIN}_live.yaml" ]] || { echo "ERROR: chart/bots/${COIN}_live.yaml missing" >&2; exit 1; }

rsync -a --delete \
  --exclude '__pycache__' --exclude 'test_*.py' --exclude '_user_ws_listen.py' \
  --include '*/' --include '*.py' --exclude '*' \
  src/ chart/files/scripts/

helm upgrade --install "${COIN}-every-tick-trader" ./chart \
  -f "chart/bots/${COIN}_every_tick.yaml" \
  -f chart/bots/creds.secret.yaml \
  -f "chart/bots/${COIN}_live.yaml" \
  -n every-tick

echo
echo ">>> ${COIN} is going LIVE. Watching startup logs (Ctrl-C to detach; bot keeps running):"
kubectl rollout status -n every-tick "deploy/${COIN}-every-tick-trader" --timeout=120s
kubectl logs -n every-tick "deploy/${COIN}-every-tick-trader" -f --tail=50
