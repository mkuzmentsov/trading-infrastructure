FROM python:3.12-slim

WORKDIR /app

# Pinned to match what we tested locally on 2026-06-12.
# Bump deliberately + rebuild + push a new tag; do not float "latest".
# hyperliquid-python-sdk must be >=0.24.0: HL spotMeta token indices are no
# longer contiguous list positions, and older SDKs IndexError in Info.__init__.
RUN pip install --no-cache-dir \
    ccxt==4.5.53 \
    hyperliquid-python-sdk==0.24.0 \
    eth-account==0.13.7 \
    PyYAML==6.0.2

# Code is NOT baked into the image — it's mounted from a ConfigMap by Helm
# (see funding-carry-bot/templates/configmap-script.yaml). The container just
# needs Python + deps. Bot is started by the deployment's `command`:
#   python -u /app/bot/main.py --config /app/config/config.yaml --state-dir /app/state
