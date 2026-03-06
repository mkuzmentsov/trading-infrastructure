# hummingbot-infra Project Memory

## Project Overview
Infrastructure-as-code for deploying crypto trading bots (Hummingbot + Freqtrade) on Hyperliquid exchange. Uses Ansible for VM provisioning and Kubernetes/Helm for container deployments.

- **Root:** `/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra`
- **Main branch:** `main`, **Dev branch:** `develop`
- **Target OS:** Ubuntu 24.04

## Top-Level Structure
```
hummingbot/     # Ansible playbook - unified Hummingbot stack (API, Dashboard, Gateway, EMQX, Redis, Postgres)
                # Also: hummingbot/k8s/ - K8s Helm chart for HL-WhiteBIT arbitrage bot
freqtrade/      # Ansible playbook + K8s Helm charts for Freqtrade copy-trading bots
hetzner-k3s/    # Hetzner Cloud K3s cluster config
util/           # Python utilities (hl_leaderboard.py - Hyperliquid leaderboard scanner)
.claude/memory/ # Claude AI session notes (this directory)
```

## Key Details
- See `freqtrade.md` for Freqtrade-specific strategies and deployment
- See `hummingbot.md` for Hummingbot stack + arbitrage bot details
- See `kubernetes.md` for K8s/Helm/Hetzner details

## Critical Gitignored Files (must create manually)
- `hummingbot/inventory.ini` - Ansible inventory
- `hummingbot/env.values.yml` - Hummingbot configuration values
- `freqtrade/inventory.ini` - Ansible inventory
- `freqtrade/env.values.yml` - Freqtrade bots configuration
- `hetzner-k3s/kubeconfig` - K3s cluster kubeconfig
- `freqtrade/k8s/helm/bots/*.yaml` - Freqtrade bot credentials (use .example as template)
- `hummingbot/k8s/helm/bots/*.yaml` - Arbitrage bot credentials (use .example as template)

## User Preferences
- Always save knowledge to memory inside the project at `.claude/memory/`
- Prefer K8s/Helm for new bot deployments (mirrors freqtrade pattern)
- K8s namespaces: `freqtrade` for Freqtrade bots, `hummingbot` for Hummingbot bots
