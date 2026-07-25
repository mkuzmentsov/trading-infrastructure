#!/usr/bin/env python3
"""pm-scout wallet — bankroll + portfolio truth.
Reads creds from every-tick-single/chart/bots/sol.secret.yaml (gitignored live
overlay; the tail-bot config). Prints:
  1. wallet USDC balance (on-chain via CLOB client — needs PK; skipped if unavailable)
  2. OPEN positions (data-api, needs address only): entry vs mark, uPnL, end date
  3. REDEEMABLE positions (resolved, claimable now)
Usage: python3 wallet.py [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SECRET_YAML = os.path.join(ROOT, "every-tick-single", "chart", "bots", "sol.secret.yaml")
DATA_API = "https://data-api.polymarket.com"


def creds() -> dict:
    """Flat-parse the credentials: block of the secret overlay (no yaml dep)."""
    out = {}
    try:
        txt = open(SECRET_YAML).read()
    except FileNotFoundError:
        sys.exit(f"creds file missing: {SECRET_YAML}")
    for key in ("polymarketPrivateKey", "polymarketAddress",
                "polymarketFunder", "polymarketSignatureType"):
        m = re.search(rf'^\s+{key}:\s*"([^"]*)"', txt, re.M)
        if m:
            out[key] = m.group(1).strip()
    return out


def _get(path: str, params: dict) -> list | dict:
    url = f"{DATA_API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "pm-scout/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def positions(user: str, redeemable: bool | None = None) -> list:
    params = {"user": user, "sizeThreshold": "0.01", "limit": 200}
    if redeemable is not None:
        params["redeemable"] = "true" if redeemable else "false"
    r = _get("/positions", params)
    return r if isinstance(r, list) else []


PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"   # Polymarket USD wrapper
ALCHEMY_ENV = "/Users/maxkuzmentsov/development/projects/my/skarbfolio/.env"


def balance(c: dict) -> float | None:
    """REAL on-chain pUSD of the funder Safe, read directly from the token —
    the CLOB balance view LAGS by tens of $ (same method as tail balance.sh)."""
    try:
        key = re.search(r'ALCHEMY_API_KEY\s*=\s*["\']?([A-Za-z0-9_\-\.]+)',
                        open(ALCHEMY_ENV).read()).group(1)
        addr = (c.get("polymarketFunder") or c.get("polymarketAddress") or "")
        addr = addr.lower().removeprefix("0x")
        req = urllib.request.Request(
            f"https://polygon-mainnet.g.alchemy.com/v2/{key}",
            data=json.dumps({"jsonrpc": "2.0", "method": "eth_call", "id": 1,
                             "params": [{"to": PUSD,
                                         "data": "0x70a08231" + "0" * 24 + addr},
                                        "latest"]}).encode(),
            headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=15))
        return int(r["result"], 16) / 1e6
    except Exception as exc:
        print(f"(balance unavailable: {exc})", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    c = creds()
    user = c.get("polymarketFunder") or c.get("polymarketAddress") or ""
    if not user:
        sys.exit("no wallet address in creds overlay")

    open_pos = [p for p in positions(user) if not p.get("redeemable")]
    redeem = positions(user, redeemable=True)
    bal = balance(c)

    if a.json:
        print(json.dumps({"balance": bal, "open": open_pos, "redeemable": redeem}))
        return

    print(f"wallet: {user}")
    print(f"USDC balance: {'$%.2f' % bal if bal is not None else 'n/a'}")

    worth = [p for p in redeem if float(p.get("currentValue") or 0) >= 0.01]
    dust = len(redeem) - len(worth)
    tot = sum(float(p.get("currentValue") or 0) for p in worth)
    print(f"\n== REDEEMABLE ({len(worth)} worth claiming, {dust} zero-value dust) ==")
    for p in sorted(worth, key=lambda x: -float(x.get("currentValue") or 0)):
        val = float(p.get("currentValue") or 0)
        print(f"  ${val:>8.2f}  {p.get('title','')[:70]}  [{p.get('outcome','')}]")
    print(f"  TOTAL claimable: ${tot:.2f}")

    print(f"\n== OPEN POSITIONS ({len(open_pos)}) ==")
    for p in sorted(open_pos, key=lambda x: -float(x.get("currentValue") or 0)):
        size = float(p.get("size") or 0)
        avg = float(p.get("avgPrice") or 0)
        cur = float(p.get("curPrice") or 0)
        val = float(p.get("currentValue") or 0)
        upnl = float(p.get("cashPnl") or 0)
        print(f"  {size:>8.1f}sh @{avg:.3f} now {cur:.3f}  val=${val:>8.2f} "
              f"uPnL={upnl:>+8.2f}  end={str(p.get('endDate',''))[:10]}  "
              f"{p.get('title','')[:56]}  [{p.get('outcome','')}]")


if __name__ == "__main__":
    main()
