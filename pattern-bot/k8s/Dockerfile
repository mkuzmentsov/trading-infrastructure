# OPTIONAL / fallback. The Helm chart reuses mkuzmentsov/funding-carry-bot:0.2
# (a superset of these deps), so you normally don't need to build this. Kept in
# case you want a dedicated pattern-bot image.
FROM python:3.12-slim

WORKDIR /app

# Live bot deps only (patterns/strategy are stdlib; pandas/numpy are backtest-only
# and NOT needed at runtime). Pinned to what we tested locally.
#   - hyperliquid-python-sdk >=0.24.0 (older SDKs IndexError on HL spotMeta)
#   - requests: Telegram notifications + HL info POSTs
RUN pip install --no-cache-dir \
    hyperliquid-python-sdk==0.24.0 \
    eth-account==0.13.7 \
    PyYAML==6.0.2 \
    requests==2.32.3

# Code is NOT baked into the image — Helm mounts bot/*.py from a ConfigMap
# (templates/configmap-script.yaml). Started by the deployment's command:
#   python -u /app/bot/main.py --config /app/config/config.yaml --state-dir /app/state
