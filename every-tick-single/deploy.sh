#!/usr/bin/env bash
# Deploy the every-tick-single PAPER fleet (single-side experiment fork). Code ships as a helm ConfigMap (no docker build):
# this script syncs src/ -> chart/files/scripts/, then helm-upgrades each coin.
# The image (mkuzmentsov/pm-btc-bot, deps only) never changes for code edits.
#
# Usage: ./deploy.sh [coin ...]     (default: btc eth sol xrp)
# Requires the Hetzner k3s context: cd <repo root> && source .dev-env-source
set -euo pipefail
cd "$(dirname "$0")"

CTX=$(kubectl config current-context)
if [[ "$CTX" != "hetzner-k3s-cluster-master1" ]]; then
  echo "ERROR: kube context is '$CTX', expected hetzner-k3s-cluster-master1." >&2
  echo "Run: cd <repo root> && source .dev-env-source" >&2
  exit 1
fi

COINS=("$@")
[[ ${#COINS[@]} -eq 0 ]] && COINS=(btc eth sol xrp)

kubectl get ns every-tick-single >/dev/null 2>&1 || kubectl create ns every-tick-single

rsync -a --delete \
  --exclude '__pycache__' --exclude 'test_*.py' --exclude '_user_ws_listen.py' \
  --include '*/' --include '*.py' --exclude '*' \
  src/ chart/files/scripts/

echo "Synced $(find chart/files/scripts -name '*.py' | wc -l | tr -d ' ') files into chart/files/scripts/"

for coin in "${COINS[@]}"; do
  helm upgrade --install "${coin}-every-tick-single" ./chart \
    -f "chart/bots/${coin}_single.yaml" -n every-tick-single
done

kubectl get pods -n every-tick-single
