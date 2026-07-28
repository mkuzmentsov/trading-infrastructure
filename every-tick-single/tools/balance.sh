#!/usr/bin/env bash
# REAL wallet balance = on-chain pUSD (Polymarket USD wrapper token).
# The CLOB get_balance_allowance view lags by tens of $ — read the token direct.
#
# The wallet is NOT hardcoded: it comes from a credentials overlay, so
# repointing the bots at another Polymarket account repoints this too.
# Resolution order:
#   1. $PM_WALLET          explicit override
#   2. $PM_SECRET_YAML     path to a credentials overlay
#   3. chart/bots/crypto.secret.yaml   (this is the BOT fleet's tool)
# The pm-scout account lives in scout.secret.yaml — check it with:
#   PM_SECRET_YAML=chart/bots/scout.secret.yaml bash tools/balance.sh
# Inside the overlay: credentials.polymarketFunder (the Safe holding the
# money) wins over polymarketAddress (the signer).
# Alchemy key comes from the skarbfolio project's .env (Polygon mainnet).
HERE="$(cd "$(dirname "$0")" && pwd)"
export PM_SECRET_YAML="${PM_SECRET_YAML:-$HERE/../chart/bots/crypto.secret.yaml}"
python3 - <<'PY'
import json, os, re, sys, urllib.request

ENV = "/Users/maxkuzmentsov/development/projects/my/skarbfolio/.env"
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # Polymarket USD wrapper


def wallet_from_overlay(path):
    try:
        text = open(path).read()
    except OSError:
        return None
    found = {}
    for field in ("polymarketFunder", "polymarketAddress"):
        m = re.search(rf'{field}\s*:\s*["\']?(0x[0-9a-fA-F]{{40}})', text)
        if m:
            found[field] = m.group(1)
    return found.get("polymarketFunder") or found.get("polymarketAddress")


wallet = os.environ.get("PM_WALLET") or wallet_from_overlay(
    os.environ["PM_SECRET_YAML"])
if not wallet:
    print("REAL BALANCE: unavailable (no wallet found in %s; "
          "set PM_WALLET to override)" % os.environ["PM_SECRET_YAML"])
    sys.exit(1)

try:
    key = re.search(r'ALCHEMY_API_KEY\s*=\s*["\']?([A-Za-z0-9_\-\.]+)',
                    open(ENV).read()).group(1)
except Exception as exc:
    print("REAL BALANCE: unavailable (no Alchemy key:", exc, ")")
    sys.exit(1)

req = urllib.request.Request(
    f"https://polygon-mainnet.g.alchemy.com/v2/{key}",
    data=json.dumps({'jsonrpc': '2.0', 'method': 'eth_call', 'id': 1,
                     'params': [{'to': PUSD,
                                 'data': '0x70a08231000000000000000000000000'
                                         + wallet[2:].lower()},
                                'latest']}).encode(),
    headers={'Content-Type': 'application/json'})
r = json.load(urllib.request.urlopen(req, timeout=15))
print(f"REAL BALANCE (on-chain pUSD): ${int(r['result'], 16) / 1e6:.2f}"
      f"  [{wallet[:10]}…]")
PY
