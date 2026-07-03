"""Standalone Polymarket user-channel listener.

Authenticates with API creds derived from the wallet private key (loaded from
a helm values YAML — default: ../bots/pm_btc_smart.yaml) and subscribes to the
user WebSocket for one or more markets. Raw messages are printed to stdout as
received, one per line, unmodified.

When no condition_id is passed on the CLI, the listener auto-discovers the
active BTC hourly market and incrementally rotates its subscription as markets
roll over (unsubscribe old, subscribe new — no re-auth).

Usage:
    python _user_ws_listen.py <condition_id> [<condition_id>...]
    python _user_ws_listen.py --yaml ../bots/pm_btc_smart_v2.yaml
    python _user_ws_listen.py --poll-secs 15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import websockets
import yaml as yaml_lib

USER_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_YAML = SCRIPT_DIR.parent.parent.parent / "bots" / "pm_btc_smart.yaml"


def _load_credentials(yaml_path: Path) -> None:
    with open(yaml_path) as handle:
        raw = yaml_lib.safe_load(handle) or {}
    creds = raw.get("credentials", {}) or {}
    mapping = {
        "polymarketPrivateKey": "POLYMARKET_PK",
        "polymarketFunder": "POLYMARKET_FUNDER",
        "polymarketSignatureType": "POLYMARKET_SIGNATURE_TYPE",
        "polymarketApiKey": "POLYMARKET_API_KEY",
        "polymarketApiSecret": "POLYMARKET_API_SECRET",
        "polymarketApiPassphrase": "POLYMARKET_API_PASSPHRASE",
    }
    for yaml_key, env_key in mapping.items():
        value = creds.get(yaml_key)
        if value and not os.environ.get(env_key):
            os.environ[env_key] = str(value)


def _derive_api_creds() -> dict[str, str]:
    # 2026-05-06: migrated to v2 SDK after Polymarket CLOB v2 cutover.
    from py_clob_client_v2 import ClobClient, ApiCreds

    pk = os.environ.get("POLYMARKET_PK", "")
    funder = os.environ.get("POLYMARKET_FUNDER", "") or None
    sig_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0") or 0)

    api_key = os.environ.get("POLYMARKET_API_KEY", "")
    api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
    api_pass = os.environ.get("POLYMARKET_API_PASSPHRASE", "")

    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=137,
        creds=ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
        if api_key else None,
        signature_type=sig_type,
        funder=funder,
    )
    if not api_key:
        creds_obj = client.create_or_derive_api_key()
        client.set_api_creds(creds_obj)
        api_key = creds_obj.api_key
        api_secret = creds_obj.api_secret
        api_pass = creds_obj.api_passphrase

    return {
        "apiKey": api_key,
        "secret": api_secret,
        "passphrase": api_pass,
    }


def _fetch_active_btc_market() -> str:
    import requests

    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={"closed": "false", "limit": 50, "order": "endDate", "ascending": "true"},
        timeout=10,
    )
    resp.raise_for_status()
    for m in resp.json():
        question = (m.get("question") or "").lower()
        if "bitcoin" in question and ("hour" in question or "up or down" in question):
            return m.get("conditionId") or ""
    return ""


async def _rotate_loop(ws, state: dict, poll_secs: float) -> None:
    """Poll the gamma API; on market change send unsubscribe(old)+subscribe(new)."""
    while True:
        try:
            await asyncio.sleep(poll_secs)
            current = await asyncio.to_thread(_fetch_active_btc_market)
            if not current or current == state["market"]:
                continue
            old = state["market"]
            await ws.send(json.dumps({"operation": "unsubscribe", "markets": [old]}))
            await ws.send(json.dumps({"operation": "subscribe", "markets": [current]}))
            state["market"] = current
            print(f"# rotated  old={old[:16]}  new={current[:16]}", file=sys.stderr)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"# rotate error: {exc}", file=sys.stderr)


async def _read_loop(ws) -> None:
    async for message in ws:
        print(message, flush=True)


async def _run(initial_markets: list[str], creds: dict[str, str],
               auto_rotate: bool, poll_secs: float) -> None:
    print(f"# connecting  markets={initial_markets}  apiKey={creds['apiKey'][:8]}...  auto={auto_rotate}",
          file=sys.stderr)
    async with websockets.connect(USER_WS_URL, ping_interval=20, ping_timeout=30) as ws:
        await ws.send(json.dumps({
            "auth": creds,
            "markets": initial_markets,
            "type": "user",
        }))
        print("# subscribed — awaiting messages", file=sys.stderr)

        tasks = [asyncio.create_task(_read_loop(ws))]
        if auto_rotate:
            state = {"market": initial_markets[0]}
            tasks.append(asyncio.create_task(_rotate_loop(ws, state, poll_secs)))

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc:
                    raise exc
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", help="Condition IDs (one or more). Omit for auto-rotate BTC.")
    ap.add_argument("--yaml", default=str(DEFAULT_YAML),
                    help=f"Helm values YAML with credentials (default: {DEFAULT_YAML})")
    ap.add_argument("--poll-secs", type=float, default=30.0,
                    help="Market rotation poll interval (auto mode only)")
    args = ap.parse_args()

    _load_credentials(Path(args.yaml))
    if not os.environ.get("POLYMARKET_PK"):
        raise SystemExit("POLYMARKET_PK not set — check YAML credentials or env")

    if args.markets:
        initial_markets = args.markets
        auto_rotate = False
    else:
        initial = _fetch_active_btc_market()
        if not initial:
            raise SystemExit("No active BTC market found — pass a condition_id explicitly")
        initial_markets = [initial]
        auto_rotate = True

    creds = _derive_api_creds()
    try:
        asyncio.run(_run(initial_markets, creds, auto_rotate, args.poll_secs))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
