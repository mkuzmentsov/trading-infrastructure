# Freqtrade K8s Deployment

Deploys Freqtrade copy-trading bots to Kubernetes using Helm. Each bot is an independent Helm release backed by its own values file.

## Prerequisites

- `helm` CLI installed
- `kubectl` configured with cluster access (`hetzner-k3s/kubeconfig`)
- Docker image pushed to registry (see [Building the image](#building-the-image))

## Structure

```
freqtrade/k8s/
├── Dockerfile                  # Custom image (freqtrade + hyperliquid-python-sdk)
└── helm/
    ├── deploy.sh               # Deploy a single bot by name
    ├── destroy.sh              # Uninstall a single bot by name
    ├── freqtrade-bot/          # Helm chart (shared by all bots)
    │   └── values.yaml         # Shared defaults (strategy, stake, resources, etc.)
    └── bots/                   # Per-bot overrides
        ├── copy_hl_ls_1.yaml
        ├── copy_hl_ls_2.yaml
        ├── copy_hl_ls_3.yaml
        └── copy_hl_ls_4.yaml
```

Each bot values file overrides only what differs: wallet addresses, Telegram token, API credentials, and ingress hostname.

## Building the Image

```bash
docker build -t <your-registry>/freqtrade-custom:latest freqtrade/k8s/
docker push <your-registry>/freqtrade-custom:latest
```

Update `image.repository` in `helm/freqtrade-bot/values.yaml` to point to your registry.

## Bot Configuration

Before deploying, edit each `helm/bots/copy_hl_ls_N.yaml` and set:

| Field | Description |
|-------|-------------|
| `exchange.walletAddress` | Your Hyperliquid wallet address |
| `exchange.privateKey` | Your Hyperliquid private key |
| `exchange.walletToCopy` | Target wallet address to mirror |
| `telegram.token` | Telegram bot token |
| `telegram.chatId` | Telegram chat ID |
| `api.password` | FreqUI login password |
| `api.jwtSecretKey` | JWT secret (random string) |
| `ingress.host` | Hostname to expose the bot UI (e.g. `bot1.yourdomain.com`) |

Shared settings (stake amount, max trades, dry run, resources) are in `helm/freqtrade-bot/values.yaml`.

## Deployment

### Deploy a single bot

```bash
freqtrade/k8s/helm/deploy.sh copy_hl_ls_1
```

### Deploy all bots

```bash
for f in freqtrade/k8s/helm/bots/*.yaml; do
  freqtrade/k8s/helm/deploy.sh "$(basename "$f" .yaml)"
done
```

### Preview changes before applying

```bash
helm diff upgrade copy-hl-ls-1 freqtrade/k8s/helm/freqtrade-bot/ \
  -f freqtrade/k8s/helm/bots/copy_hl_ls_1.yaml \
  --namespace freqtrade
```

> Requires `helm-diff` plugin: `helm plugin install https://github.com/databus23/helm-diff`

## Uninstallation

### Remove a single bot

```bash
freqtrade/k8s/helm/destroy.sh copy_hl_ls_1
```

### Remove all bots

```bash
for f in freqtrade/k8s/helm/bots/*.yaml; do
  freqtrade/k8s/helm/destroy.sh "$(basename "$f" .yaml)"
done
```

> Note: PersistentVolumeClaims are not deleted automatically. To fully clean up:
> ```bash
> kubectl delete pvc -l app.kubernetes.io/instance=copy-hl-ls-1 --namespace freqtrade
> ```

## Monitoring

### List all bot releases

```bash
helm list --namespace freqtrade
```

### Check pod status

```bash
kubectl get pods --namespace freqtrade
```

### Stream bot logs

```bash
kubectl logs -f deploy/copy-hl-ls-1-freqtrade-bot --namespace freqtrade
```

### Check ingress endpoints

```bash
kubectl get ingress --namespace freqtrade
```

## Adding a New Bot

1. Copy an existing values file:
   ```bash
   cp freqtrade/k8s/helm/bots/copy_hl_ls_1.yaml freqtrade/k8s/helm/bots/copy_hl_ls_5.yaml
   ```
2. Edit `copy_hl_ls_5.yaml` — set wallet addresses, Telegram token, ingress host.
3. Deploy:
   ```bash
   freqtrade/k8s/helm/deploy.sh copy_hl_ls_5
   ```
