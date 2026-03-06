#!/bin/bash
# Writes connector config files from environment variables then starts Hummingbot.
# Credentials are injected by Kubernetes as env vars from a Secret.
set -euo pipefail

CONF_DIR="/home/hummingbot/conf/connectors"
mkdir -p "$CONF_DIR"

# --- Hyperliquid Perpetual connector ---
cat > "$CONF_DIR/hyperliquid_perpetual.yml" <<EOF
connector: hyperliquid_perpetual
hyperliquid_perpetual_api_key: "${HL_WALLET_ADDRESS}"
hyperliquid_perpetual_secret_key: "${HL_PRIVATE_KEY}"
hyperliquid_perpetual_use_vault: false
EOF

# --- WhiteBIT connector ---
cat > "$CONF_DIR/whitebit.yml" <<EOF
connector: whitebit
whitebit_api_key: "${WB_API_KEY}"
whitebit_secret_key: "${WB_SECRET_KEY}"
EOF

echo "Connector configs written."

exec /opt/conda/run -n hummingbot python /home/hummingbot/bin/hummingbot_quickstart.py \
    --headless \
    --config-password "" \
    --script hl_wb_arb.py
