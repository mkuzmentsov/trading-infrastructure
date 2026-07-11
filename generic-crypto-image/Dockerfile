# generic-crypto-image — shared deps-only base for the crypto bots.
# Code ships at runtime via a ConfigMap mounted at /app/scripts (same pattern as
# the old pm-btc-bot). This image bundles the trading SDKs AND the ML stack
# (numpy/pandas/scikit-learn/lightgbm) so bots can load models without a rebuild.
#
# python 3.12 + scikit-learn 1.9.0 match the model-training env
# (every-tick-single/backtest/fiftycent) so pickled models load cleanly.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    # ── Polymarket / exchange SDKs (from pm-btc-bot) ──────────────────────────
    websockets==12.0 \
    py-clob-client==0.34.6 \
    py-clob-client-v2==1.0.0 \
    requests==2.32.3 \
    # ── on-chain (redemptions / relayer) ─────────────────────────────────────
    eth-account \
    eth-abi \
    eth-keys \
    eth-utils \
    # ── ML / data stack ──────────────────────────────────────────────────────
    numpy \
    pandas \
    scipy \
    scikit-learn==1.9.0 \
    lightgbm==4.6.0

CMD ["python", "-u", "/app/scripts/main.py"]
