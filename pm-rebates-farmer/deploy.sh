#!/usr/bin/env bash
# Deploy pm-rebates-farmer (LIVE). cd repo root && source .dev-env-source first.
set -euo pipefail
cd "$(dirname "$0")"
[[ "$(kubectl config current-context)" == "hetzner-k3s-cluster-master1" ]] || { echo "wrong kube context"; exit 1; }
kubectl get ns pm-rebates-farmer >/dev/null 2>&1 || kubectl create ns pm-rebates-farmer
rsync -a --delete --exclude '__pycache__' --exclude 'test_*.py' --include '*/' --include '*.py' --exclude '*' src/ chart/files/scripts/
helm upgrade --install pm-rebates-farmer-btc ./chart -f chart/bots/btc.secret.yaml -n pm-rebates-farmer
kubectl get pods -n pm-rebates-farmer
