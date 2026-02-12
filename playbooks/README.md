# Hummingbot Provisioning Playbook

This playbook installs Hummingbot Bot and Hummingbot API on Ubuntu 24.04 hosts.

## Files

- `install_hummingbot_stack.yml`: Main provisioning playbook.
- `inventory.example.ini`: Example inventory for target instances.
- `tasks/users.yml`: User, group, and home directory setup.
- `tasks/system_packages.yml`: Base apt package installation.
- `tasks/docker.yml`: Docker repository, packages, and docker group setup.
- `tasks/anaconda.yml`: Anaconda installer download and installation.
- `tasks/hummingbot_bot.yml`: Hummingbot bot download, extract, and `make setup`.
- `tasks/hummingbot_api.yml`: Hummingbot API download, extract, and `make setup`.

## What it does

- Creates the `hummingbot` group and user.
- Installs Docker and adds `hummingbot` to the `docker` group.
- Installs required tools (`make`, `unzip`, and dependencies).
- Installs Anaconda3 into `/home/hummingbot/anaconda3`.
- Downloads and extracts:
  - `hummingbot` at `v{{ hummingbot_bot_version }}`
  - `hummingbot-api` at `v{{ hummingbot_api_version }}`
- Runs `make setup` in both projects.

## Usage

1. Copy and edit inventory:

   ```bash
   cp playbooks/inventory.example.ini playbooks/inventory.ini
   ```

2. Run playbook:

   ```bash
   ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml
   ```

3. Override versions if needed:

   ```bash
   ansible-playbook -i playbooks/inventory.ini playbooks/install_hummingbot_stack.yml \
     -e hummingbot_bot_version=2.12.0 \
     -e hummingbot_api_version=2.1.0
   ```
