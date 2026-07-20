#!/usr/bin/env bash
# REAL wallet balance = on-chain pUSD (Polymarket USD wrapper token) for the
# shared Safe 0xD632C1e14323B75456eA0A58d90B05fB7B7a1b2F.
# The CLOB get_balance_allowance view lags by tens of $ — read the token direct.
# Uses the Alchemy key from the skarbfolio project's .env (Polygon mainnet).
python3 - <<'PY'
import json, re, urllib.request
ENV="/Users/maxkuzmentsov/development/projects/my/skarbfolio/.env"
try:
    key=re.search(r'ALCHEMY_API_KEY\s*=\s*["\']?([A-Za-z0-9_\-\.]+)', open(ENV).read()).group(1)
except Exception as e:
    print("REAL BALANCE: unavailable (no Alchemy key:", e, ")"); raise SystemExit
PUSD="0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # Polymarket USD wrapper
SAFE="d632c1e14323b75456ea0a58d90b05fb7b7a1b2f"      # Safe (no 0x)
req=urllib.request.Request(f"https://polygon-mainnet.g.alchemy.com/v2/{key}",
    data=json.dumps({'jsonrpc':'2.0','method':'eth_call','id':1,
        'params':[{'to':PUSD,'data':'0x70a08231000000000000000000000000'+SAFE},'latest']}).encode(),
    headers={'Content-Type':'application/json'})
r=json.load(urllib.request.urlopen(req, timeout=15))
print(f"REAL BALANCE (on-chain pUSD): ${int(r['result'],16)/1e6:.2f}")
PY
