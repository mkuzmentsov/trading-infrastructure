#!/usr/bin/env bash
# Deploy Loki + Grafana log stack to the K3s cluster.
# Promtail runs as a DaemonSet and auto-discovers all pod logs — no per-bot config needed.
set -euo pipefail

NAMESPACE="monitoring"
RELEASE="loki-stack"
RETENTION_HOURS="${LOKI_RETENTION_HOURS:-720}"  # 30 days default
STORAGE_SIZE="${LOKI_STORAGE_SIZE:-10Gi}"
ADMIN_PASSWORD="${GRAFANA_PASSWORD:-}"

if [[ -z "$ADMIN_PASSWORD" ]]; then
  echo "Error: set GRAFANA_PASSWORD env var before deploying."
  echo "  export GRAFANA_PASSWORD=your-secure-password"
  exit 1
fi

echo "Adding Grafana Helm repo..."
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

echo "Deploying $RELEASE to namespace '$NAMESPACE'..."
helm upgrade --install "$RELEASE" grafana/loki-stack \
  --namespace "$NAMESPACE" --create-namespace \
  --set grafana.enabled=true \
  --set grafana.adminPassword="$ADMIN_PASSWORD" \
  --set promtail.enabled=true \
  --set loki.persistence.enabled=true \
  --set loki.persistence.size="$STORAGE_SIZE" \
  --set "loki.config.chunk_store_config.max_look_back_period=${RETENTION_HOURS}h" \
  --set "loki.config.table_manager.retention_period=${RETENTION_HOURS}h" \
  --set "loki.config.table_manager.retention_deletes_enabled=true"

echo ""
echo "Done. Access Grafana locally:"
echo "  kubectl port-forward svc/${RELEASE}-grafana 3000:80 -n $NAMESPACE"
echo "  open http://localhost:3000  (admin / \$GRAFANA_PASSWORD)"
