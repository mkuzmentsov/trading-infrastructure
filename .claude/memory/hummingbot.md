# Hummingbot Details

## Existing Stack (Ansible-managed)
- Deployed via Ansible playbook in `hummingbot/`
- Components: API, Dashboard, Gateway, EMQX, Redis, Postgres
- Config: `hummingbot/inventory.ini` + `hummingbot/env.values.yml` (both gitignored)

## Arbitrage Bot (K8s/Helm - added 2026-03)

### Purpose
Cross-exchange arbitrage: **Hyperliquid perpetuals** ↔ **WhiteBIT spot**

### Key Files
```
hummingbot/k8s/
├── Dockerfile                         # Official HB + WhiteBIT connector from their fork
├── entrypoint.sh                      # Writes connector YAMLs from env vars, starts HB headless
└── helm/
    ├── deploy.sh / destroy.sh
    ├── bots/
    │   └── hl_wb_arb_1.yaml.example   # Template for credentials (gitignored)
    └── hummingbot-arb/                # Single reusable Helm chart
        ├── Chart.yaml / values.yaml
        ├── files/scripts/hl_wb_arb.py  # Strategy (Script v2)
        └── templates/
            ├── secret.yaml             # Credentials + script config YAML
            ├── configmap-script.yaml   # Python script as ConfigMap
            ├── deployment.yaml
            ├── service.yaml / ingress.yaml / pvc.yaml
```

### Strategy: `hl_wb_arb.py`
Two modes per pair (BTC, ETH, configurable):
1. **Instant arb** — fires when net spread (after fees) > `min_profitability` (default 0.2%)
2. **Carry/basis arb** — delta-neutral: long WB spot + short HL perp when basis > 0.3% + positive funding; closes when basis < 0.05%

Uses Hummingbot Script v2 (`ScriptStrategyBase`) with `HLWBArbitrageConfig` pydantic model.

### Exchange Details
- **Hyperliquid**: taker fee 0.035%, has testnet (`https://api.hyperliquid-testnet.xyz`)
- **WhiteBIT**: taker fee 0.1%, **no testnet** — use Hummingbot paper trade mode instead
- WhiteBIT NOT in official Hummingbot; connector cloned from `https://github.com/whitebit-exchange/hummingbot`

### Credential Flow
- Credentials stored as K8s Secret (`hl_wallet_address`, `hl_private_key`, `wb_api_key`, `wb_secret_key`)
- `entrypoint.sh` reads env vars → writes `conf/connectors/hyperliquid_perpetual.yml` + `whitebit.yml`
- Script config (pairs, thresholds, fees) stored in same Secret as `script_config_yml` key → mounted at `conf/scripts/hl_wb_arb.yml`

### Testnet / Paper Trading
- **HL testnet**: set `hyperliquid.useTestnet: true` in bot values + wire URL override in entrypoint
- **WB paper trade**: add `--paper-trade` flag to entrypoint startup command (env var `PAPER_TRADE=true`)
- Paper trade recommended for initial validation since WB has no testnet

### Docker Image
- Base: `hummingbot/hummingbot:latest`
- Adds: WhiteBIT connector from `https://github.com/whitebit-exchange/hummingbot`
- Published as: `mkuzmentsov/hummingbot-wb:0.1`

### Deploy Commands
```bash
# Build image (once or on strategy changes)
docker build -t mkuzmentsov/hummingbot-wb:0.1 hummingbot/k8s/
docker push mkuzmentsov/hummingbot-wb:0.1

# Deploy
cp hummingbot/k8s/helm/bots/hl_wb_arb_1.yaml.example hummingbot/k8s/helm/bots/hl_wb_arb_1.yaml
# fill credentials...
hummingbot/k8s/helm/deploy.sh hl_wb_arb_1

# Monitor / remove
kubectl logs -f deploy/hl-wb-arb-1 -n hummingbot
hummingbot/k8s/helm/destroy.sh hl_wb_arb_1
```

### Hummingbot vs Freqtrade for Arbitrage
| | Hummingbot | Freqtrade |
|---|---|---|
| Built-in arb strategies | Yes | No |
| Multi-exchange simultaneously | Yes | No (~5-60s loop) |
| WhiteBIT support | Via community fork | N/A |
