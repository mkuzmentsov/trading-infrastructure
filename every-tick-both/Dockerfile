FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# 2026-05-06: added py-clob-client-v2 after Polymarket CLOB v2 cutover (~Apr 30
# bumped the EIP-712 domain version, breaking every signature from the legacy
# v0.34.6 SDK with `order_version_mismatch`). Bot scripts now import exclusively
# from py_clob_client_v2; the legacy package is kept installed during the
# transition for any incidental utility imports — remove once verified clean.
RUN pip install --no-cache-dir \
    websockets==12.0 \
    py-clob-client==0.34.6 \
    py-clob-client-v2==1.0.0 \
    requests==2.32.3 \
    lightgbm==4.6.0

# Bot source is baked into the image (was ConfigMap-injected in the old
# polymarket-btc-5m-bot project; this project ships src/ directly).
COPY src /app/scripts

CMD ["python", "-u", "/app/scripts/main.py"]
