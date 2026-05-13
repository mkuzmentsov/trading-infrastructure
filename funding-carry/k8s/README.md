# funding-carry K8s deployment

Deploys the `funding-carry/bot/` strategy as a single Helm release per "bot"
(a coin basket + credential pair). Mirrors the pattern used by
`polymarket/k8s/helm/polymarket-1h-bot`.

## Layout

```
funding-carry/k8s/
├── Dockerfile                       python:3.12-slim + ccxt/hyperliquid-sdk/eth-account/PyYAML
└── helm/
    ├── deploy.sh                    deploy ./bots/<name>.yaml as release <name|_→->
    ├── destroy.sh                   uninstall (manual position-flatten first!)
    ├── bots/
    │   └── fc_btc_200.yaml.example  $200 BTC test overlay (copy → fill creds → deploy)
    └── funding-carry-bot/           shared chart
        ├── Chart.yaml
        ├── values.yaml              defaults; full schema mirrors bot/config.example.yaml
        ├── files/bot/               populated at deploy time (rsynced from ../../bot/)
        └── templates/
            ├── configmap-script.yaml   mounts files/bot/*.py at /app/bot
            ├── secret.yaml             renders botConfig at /app/config/config.yaml
            ├── pvc.yaml                /app/state for fc_state.json (regime flags)
            └── deployment.yaml         python -u /app/bot/main.py --config ... --state-dir ...
```

The bot's Python source is **not** baked into the image — `deploy.sh` rsyncs
`../bot/*.py` into the chart's `files/bot/` and Helm bundles them into a
ConfigMap. Strategy tweaks are a 1-second redeploy, no Docker rebuild.

## Prerequisites

- `helm` (3.x) + `kubectl` configured against the target cluster.
- A registry holding the bot image. The chart defaults to
  `mkuzmentsov/funding-carry-bot:0.1` — change in `funding-carry-bot/values.yaml`
  before first deploy.
- An HL **API wallet** (not your main key) — `app.hyperliquid.xyz` → API.
- A Kraken Pro API key with trade permission (no withdrawal).
- USDC funded into your HL perp account; USD/USDT funded on Kraken.

## Build & push the image (one-time, or on dep bump)

```bash
docker build -t mkuzmentsov/funding-carry-bot:0.1 funding-carry/k8s/
docker push     mkuzmentsov/funding-carry-bot:0.1
```

Bump the tag in `funding-carry-bot/values.yaml` when you rebuild.

## Deploy

1. Copy the example overlay and fill credentials (the real file is gitignored):
   ```bash
   cp funding-carry/k8s/helm/bots/fc_btc_200.yaml.example \
      funding-carry/k8s/helm/bots/fc_btc_200.yaml
   $EDITOR funding-carry/k8s/helm/bots/fc_btc_200.yaml
   ```
2. Deploy (keep `dry_run: true` for the first 1–2 days):
   ```bash
   ./funding-carry/k8s/helm/deploy.sh fc_btc_200
   ```
3. Watch:
   ```bash
   kubectl logs -f deploy/fc-btc-200 -n funding-carry
   ```
   You want `STATE {...}` lines with sensible `px`, `funding_apr`, balances.
   In dry-run any "[DRY-RUN] HL would: OPEN SHORT BTC ..." is the action it
   WOULD have placed live.
4. Flip live: edit the overlay's `botConfig.dry_run: false`, re-run `deploy.sh`.
   The Secret's checksum annotation rolls the pod automatically.

## Iteration

| Change                                  | What to do                                           |
|-----------------------------------------|------------------------------------------------------|
| Strategy code (`bot/*.py`)              | `./deploy.sh <name>` — rsync + helm upgrade          |
| Config (sizing, thresholds, credentials)| Edit `bots/<name>.yaml`, `./deploy.sh <name>`        |
| Python deps                             | Edit `k8s/Dockerfile`, bump `image.tag`, rebuild     |

## Common ops

```bash
helm list -n funding-carry                                 # all releases
kubectl get pods -n funding-carry                          # pod status
kubectl logs -f deploy/fc-btc-200 -n funding-carry         # live logs
kubectl exec -it deploy/fc-btc-200 -n funding-carry -- /bin/bash    # shell
kubectl get pvc -n funding-carry                           # state volumes

# Inspect the rendered config (sanity-check creds went through):
kubectl get secret fc-btc-200-secret -n funding-carry -o jsonpath='{.data.config\.yaml}' \
  | base64 -d

# Tear down (manual flatten first!):
./funding-carry/k8s/helm/destroy.sh fc_btc_200
```

## Safety notes

- The bot opens **real positions** when `dry_run: false`. Start with the $200
  overlay (one ~$130 BTC pair), L=2.
- `Recreate` deployment strategy + `ReadWriteOnce` PVC together guarantee
  only one pod runs at a time. Two pods would double-open positions.
- `fc_state.json` (regime-exit flags) lives on the PVC. **Do not delete the
  PVC** while regime-exited coins exist — the bot will re-open them on the
  next loop.
- `destroy.sh` does NOT close positions. Flatten manually on HL + Kraken
  first, or let the bot run with explicit close logic before uninstall.
- Hardcoded HL slippage cap is 30 bps for the v1 IOC-taker leg; at $130
  that's ~$0.04 max, irrelevant for a test.
