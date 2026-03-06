# Freqtrade Details

## Exchange
- **Exchange:** Hyperliquid (Futures/Perpetuals)
- **SDK:** `hyperliquid-python-sdk` (pip-installed into custom Docker image)
- **Trading mode:** Futures/margin

## Strategies

### copy_hl (simpler copy trading)
- File: `freqtrade/templates/strategies/copy_hl.py.j2`
- Copies positions from a single target Hyperliquid wallet
- Basic entry/exit mirroring

### copy_hl_ls (long/short copy trading - main active strategy)
- File: `freqtrade/templates/strategies/copy_hl_ls.py.j2`
- Also rendered into K8s ConfigMap: `freqtrade/k8s/helm/freqtrade-bot/templates/configmap-strategy.yaml`
- Features:
  - Tracks both long and short positions
  - Records position history to CSV files
  - Telegram notifications (optional)
  - REST API control endpoints (enable/disable bot, force entry)
  - Weighted position sizing (proportional to copied wallet)
  - Min stake: 12 (set in config)
  - Whitelist auto-populated from copied positions

### sample_strategy
- Basic example for testing/development

## Bot Configuration (env.values.yml format)
```yaml
freqtrade_base_image: freqtradeorg/freqtrade:stable
freqtrade_image: freqtrade_custom:latest
freqtrade_dry_run: true   # false for live trading
bots:
  copy_hl_1:
    strategy: copy_hl
    ui_port: 8080
    hyperliquid_wallet_to_copy: "0x..."   # target wallet to mirror
    my_wallet: "0x..."                     # user's own wallet
    my_secret: "0x..."                     # user's private key
    telegram:
      enabled: true
      telegram_token: "YOUR_TOKEN"
      telegram_chat_id: "YOUR_CHAT_ID"
  copy_hl_ls_1:
    strategy: copy_hl_ls
    ui_port: 8082
    ...
```

## K8s Helm Structure
```
freqtrade/k8s/helm/
├── deploy.sh / destroy.sh
├── freqtrade-bot/          # Single reusable Helm chart
│   ├── Chart.yaml
│   ├── values.yaml         # Shared defaults
│   ├── files/strategies/copy_hl_ls.py
│   └── templates/
│       ├── deployment.yaml / service.yaml / ingress.yaml
│       ├── secret.yaml          # Generates config.json
│       ├── configmap-strategy.yaml
│       └── pvc.yaml
└── bots/                   # Per-bot overrides (gitignored)
    ├── copy_hl_ls_1.yaml
    └── *.yaml.example
```

## Freqtrade Config Template
- Template: `freqtrade/templates/configs/copy_hl_ls.config.json.j2`
- Key settings: `stake_amount`, `max_open_trades`, `dry_run`, `api_server` credentials
- FreqUI accessible via `http://<host>:<ui_port>`

## Docker Image
- Base: `freqtradeorg/freqtrade:stable`
- Adds: `hyperliquid-python-sdk` via pip
- Published as: `mkuzmentsov/freqtrade-hl:0.1`

## Deploy Commands
```bash
freqtrade/k8s/helm/deploy.sh copy_hl_ls_1
freqtrade/k8s/helm/destroy.sh copy_hl_ls_1
kubectl logs -f deploy/copy-hl-ls-1 -n freqtrade
helm list -n freqtrade
```

## Leaderboard Utility
File: `util/hl_leaderboard.py`
- Fetches public Hyperliquid leaderboard
- Weighted scoring: month_roi (50%) + week_roi (30%) + day_roi (20%)
- Filters by min account balance, profitability
- Rate limit: 0.3s between API calls
- Outputs wallet addresses for copy trading

```bash
python3 util/hl_leaderboard.py
python3 util/hl_leaderboard.py --top 20 --min-account 100000
python3 util/hl_leaderboard.py --sort month_roi --min-roi-month 0.05
# Output saved to: util/output/YYYYMMDD.output
```
