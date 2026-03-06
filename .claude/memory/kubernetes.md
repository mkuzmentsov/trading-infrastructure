# Kubernetes / Helm / Hetzner Details

## Cluster
- **Provider:** Hetzner Cloud
- **Distribution:** K3s
- **Config:** `hetzner-k3s/cluster.yaml`
- **Kubeconfig:** `hetzner-k3s/kubeconfig` (gitignored)
- **Tool:** `hetzner-k3s` CLI (https://vitobotta.github.io/hetzner-k3s/)

```yaml
# cluster.yaml summary
cluster_name: hetzner-k3s-cluster
k3s_version: v1.35.1+k3s1
masters_pool:
  instance_type: cx23   # 1 master
worker_node_pools:
  - instance_type: cx23  # 1 worker
    location: nbg1
```

## Cluster Lifecycle
```bash
export HCLOUD_TOKEN=<your-token>
hetzner-k3s create --config hetzner-k3s/cluster.yaml
export KUBECONFIG=./hetzner-k3s/kubeconfig

hetzner-k3s delete --config hetzner-k3s/cluster.yaml
```

## Helm Chart Pattern (used by both Freqtrade and Hummingbot bots)
- One chart per bot type, multiple instances via per-bot values files
- Per-bot values files are gitignored (`bots/*.yaml`), only `.example` files committed
- `deploy.sh <name>` / `destroy.sh <name>` scripts for lifecycle management
- Checksums in deployment annotations auto-restart pods on config/strategy changes
- Strategy/script mounted via ConfigMap; credentials via Secret

## Namespaces
- `freqtrade` — Freqtrade copy-trading bots
- `hummingbot` — Hummingbot arbitrage bots

## Ingress
- Class: `nginx`
- TLS optional per bot (`ingress.tls.enabled`)

## Common kubectl Commands
```bash
# List all bots
helm list -n freqtrade
helm list -n hummingbot

# Logs
kubectl logs -f deploy/<release-name> -n freqtrade
kubectl logs -f deploy/<release-name> -n hummingbot

# Delete PVCs after destroy (not automatic)
kubectl delete pvc -l app.kubernetes.io/instance=<release> -n <namespace>
```
