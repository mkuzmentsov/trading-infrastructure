# Hummingbot Provisioning Playbook

This playbook installs a unified Hummingbot stack (API + Dashboard + Gateway + EMQX + Redis + Postgres) on Ubuntu 24.04 hosts using Docker Compose.

## Files

- `install_hummingbot_stack.yml`: Main provisioning playbook.
- `inventory.example.ini`: Example inventory for target instances.
- `env.values.example.yml`: Example vars file for template env mode.
- `tasks/users.yml`: User, group, and home directory setup.
- `tasks/system_packages.yml`: Base apt package installation.
- `tasks/docker.yml`: Docker repository, packages, and docker group setup.
- `tasks/compose_stack.yml`: Unified stack deployment with Docker Compose.
- `templates/docker-compose.yml.j2`: Single compose file for bot, api, redis, and postgres.
- `templates/hummingbot.env.example.j2`: Example environment file template.
- `templates/hummingbot.env.j2`: `.env` template rendered from Ansible variables.

## What it does

- Creates the `hummingbot` group and user.
- Installs Docker and adds `hummingbot` to the `docker` group.
- Creates `/home/hummingbot/stack`.
- Deploys one docker compose file with:
  - `hummingbot-api`
  - `dashboard`
  - `gateway`
  - `emqx`
  - `redis`
  - `postgres`
- Supports two `.env` modes:
  - `manual`: creates only `.env.example` and requires user-provided `.env`
  - `template`: renders `.env` from vars passed to Ansible
- Starts the stack with `docker compose up -d` once `.env` exists.

## Usage

1. Copy and edit inventory:

   ```bash
   cp playbooks/inventory.example.ini playbooks/inventory.ini
   ```

2. Choose one of two env workflows.

### Option A: manual `.env`

Run playbook once to provision host and generate `.env.example`:

   ```bash
   ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml
   ```

   The playbook will stop with a message because `.env` is intentionally required.

On target host, create real env file from example:

   ```bash
   cp /home/hummingbot/stack/.env.example /home/hummingbot/stack/.env
   # edit /home/hummingbot/stack/.env with real values
   ```

Re-run playbook to pull images and start containers:

   ```bash
   ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml
   ```

### Option B: render `.env` from Ansible vars

Pass env values directly to Ansible and render `.env` automatically:

```bash
ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml \
  -e hummingbot_env_mode=template \
  -e hummingbot_api_image=ghcr.io/hummingbot/hummingbot-api:latest \
  -e hummingbot_dashboard_image=hummingbot/dashboard:latest \
  -e hummingbot_gateway_image=hummingbot/gateway:latest \
  -e hummingbot_tz=UTC \
  -e hummingbot_api_port=8000 \
  -e hummingbot_dashboard_port=8501 \
  -e hummingbot_gateway_port=15888 \
  -e hummingbot_gateway_passphrase='replace_me' \
  -e hummingbot_dashboard_auth_system_enabled=False \
  -e hummingbot_dashboard_backend_api_host=hummingbot-api \
  -e hummingbot_dashboard_backend_api_port=8000 \
  -e hummingbot_broker_host=emqx \
  -e hummingbot_broker_port=1883 \
  -e hummingbot_postgres_db=hummingbot \
  -e hummingbot_postgres_user=hummingbot \
  -e hummingbot_postgres_password='replace_me' \
  -e hummingbot_redis_password='replace_me'
```

You can also put these vars into a yaml file and pass it with:

```bash
ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml \
  --extra-vars @playbooks/env.values.yml
```
