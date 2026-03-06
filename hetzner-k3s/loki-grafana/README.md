# Loki + Grafana — Log Aggregation for K3s

Centralised log viewing for all bots (Freqtrade, Hummingbot) running in the cluster.

## Why Loki and not ELK / OpenSearch

ELK and OpenSearch index full log text and need **4–8 GB RAM just for Elasticsearch** — more than the entire cx23 node has. They would starve the bots.

Loki only indexes **labels** (namespace, pod, container) and stores raw log lines. The full stack uses ~200 MB RAM. Promtail runs as a DaemonSet and auto-discovers every pod's logs with zero per-bot configuration.

## Stack

| Component | Role |
|---|---|
| **Loki** | Log storage and query engine |
| **Promtail** | DaemonSet log collector (tails all pod logs automatically) |
| **Grafana** | Dashboard + LogQL query UI |

## Deploy

```bash
export KUBECONFIG=../kubeconfig
export GRAFANA_PASSWORD=your-secure-password

# Optional overrides (defaults shown):
# export LOKI_RETENTION_HOURS=720   # 30 days
# export LOKI_STORAGE_SIZE=10Gi

./deploy.sh
```

## Access locally

This is a private cluster — use the proxy script to forward Grafana to your machine:

```bash
./proxy.sh          # forwards to http://localhost:3000
./proxy.sh 3001     # use a different local port if 3000 is taken
```

Open **http://localhost:3000** and log in with `admin` / `$GRAFANA_PASSWORD`.

Grafana has Loki pre-wired as a datasource. Go to **Explore → Loki** to query logs.

## Querying logs (LogQL)

### All logs from a namespace
```logql
{namespace="freqtrade"}
{namespace="hummingbot"}
```

### Specific bot
```logql
{namespace="freqtrade", pod=~"copy-hl-ls-1.*"}
{namespace="freqtrade", pod=~"copy-hl-ls-2.*"}
```

### Filter by keyword
```logql
{namespace="freqtrade"} |= "ERROR"
{namespace="freqtrade"} |= "Extra positions"
{namespace="freqtrade"} |= "Missing positions"
{namespace="freqtrade"} |= "force_exit"
{namespace="freqtrade"} |= "Missed exit detected"
{namespace="freqtrade"} |= "Available balance"
```

### Combine namespace + keyword
```logql
{namespace="freqtrade", pod=~"copy-hl-ls-1.*"} |= "force_exit"
```

### Regex filter
```logql
{namespace="freqtrade"} |~ "ERROR|WARNING"
```

## Remove

```bash
./destroy.sh

# Also delete the log storage PVC if you want a clean removal:
kubectl delete pvc -l app=loki -n monitoring
```

## Retention

Default: **30 days** (720 hours). Change with `LOKI_RETENTION_HOURS` before deploying, or upgrade the release:

```bash
LOKI_RETENTION_HOURS=360 GRAFANA_PASSWORD=your-password ./deploy.sh  # 15 days
```
