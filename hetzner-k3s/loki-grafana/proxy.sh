#!/usr/bin/env bash
# Forward Grafana to localhost:3200.
# Run this while working — Ctrl+C to stop.
set -euo pipefail

NAMESPACE="monitoring"
RELEASE="loki-stack"
LOCAL_PORT="${1:-3200}"

echo "Forwarding Grafana → http://localhost:${LOCAL_PORT}"
echo "Press Ctrl+C to stop."
echo ""
kubectl port-forward "svc/${RELEASE}-grafana" "${LOCAL_PORT}:80" -n "$NAMESPACE"
