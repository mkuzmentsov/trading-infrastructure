# Freqtrade Provisioning Playbook

This playbook installs a Freqtrade instance on Ubuntu 24.04 hosts using Docker Compose.

## Files

- `install_freqtrade_stack.yml`: Main provisioning playbook.
- `inventory.example.ini`: Example inventory for target instances.
- `env.values.example.yml`: Example vars file for passing configuration values to Ansible.
- `tasks/users.yml`: User, group, and home directory setup.
- `tasks/system_packages.yml`: Base apt package installation.
- `tasks/docker.yml`: Docker repository, packages, and docker group setup.
- `tasks/compose_stack.yml`: Freqtrade stack deployment with Docker Compose.
- `templates/docker-compose.yml.j2`: Compose file template for Freqtrade.
- `templates/config.json.j2`: Freqtrade configuration template.
- `templates/SampleStrategy.py.j2`: Sample strategy template.

## What it does

- Creates the `freqtrade` group and user.
- Installs Docker and adds `freqtrade` to the `docker` group.
- Creates `/home/freqtrade/stack` and necessary subdirectories for `user_data`.
- Deploys a docker-compose file with the Freqtrade service.
- Renders the Freqtrade `config.json` from Ansible variables.
- Starts the stack with `docker compose up -d`.

## Usage

1. Copy and edit inventory:

   ```bash
   cp freqtrade/inventory.example.ini freqtrade/inventory.ini
   ```

2. Provision the host and deploy the stack:

   You can pass configuration values directly to Ansible or use a YAML file.

   ### Option A: Using a YAML file (Recommended)

   Create `freqtrade/env.values.yml` (you can start from `freqtrade/env.values.example.yml`):

   ```bash
   cp freqtrade/env.values.example.yml freqtrade/env.values.yml
   # Edit freqtrade/env.values.yml with your real values
   ```

   Run the playbook:

   ```bash
   ansible-playbook -i freqtrade/inventory.ini freqtrade/install_freqtrade_stack.yml \
     --extra-vars @freqtrade/env.values.yml
   ```

   ### Option B: Passing vars directly

   ```bash
   ansible-playbook -i freqtrade/inventory.ini freqtrade/install_freqtrade_stack.yml \
     -e freqtrade_hyperliquid_wallet='your_wallet_address' \
     -e freqtrade_hyperliquid_secret='your_secret' \
     -e freqtrade_api_password='your_password'
   ```

## Configuration Variables

The following variables can be customized:

- `freqtrade_image`: The Docker image to use (default: `freqtradeorg/freqtrade:stable`).
- `freqtrade_ui_port`: Port for the Freqtrade API/bundled UI (default: `8080`).
- `frequi_image`: The Docker image for standalone UI (default: `freqtradeorg/frequi:latest`).
- `frequi_port`: Port for the standalone Freqtrade UI (default: `3000`).
- `freqtrade_strategy`: Strategy to run (default: `SampleStrategy`).
- `freqtrade_hyperliquid_wallet`: Hyperliquid wallet address.
- `freqtrade_hyperliquid_secret`: Hyperliquid API secret (signing key).
- `freqtrade_jwt_secret_key`: JWT secret for API server.
- `freqtrade_api_user`: API server username.
- `freqtrade_api_password`: API server password.
