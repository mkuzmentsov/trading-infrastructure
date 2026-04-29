"""
Standalone test: connect to Polymarket RTDS BTC/USD price WebSocket and print
every incoming message.

Usage:
    python3 test_rtds_btc_ws.py

Env overrides:
    RTDS_URL     (default: wss://ws-live-data.polymarket.com)
    RTDS_SYMBOL  (default: btc/usd)
    RTDS_TOPIC   (default: crypto_prices_chainlink)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import websockets

URL = os.getenv("RTDS_URL", "wss://ws-live-data.polymarket.com")
SYMBOL = os.getenv("RTDS_SYMBOL", "btc_cr/usd_fx")
TOPIC = os.getenv("RTDS_TOPIC", "crypto_prices_chainlink")


def _build_subscribe() -> str:
    return json.dumps(
        {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": TOPIC,
                    "type": "*",
                    "filters": json.dumps({"symbol": SYMBOL}, separators=(",", ":")),
                }
            ],
        }
    )


def _fmt_ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


async def run() -> None:
    sub = _build_subscribe()
    print(f"[{_fmt_ts()}] Connecting to {URL} …", flush=True)
    async with websockets.connect(URL, ping_interval=None, ping_timeout=None) as ws:
        print(f"[{_fmt_ts()}] Connected. Subscribing: {sub}", flush=True)
        await ws.send(sub)
        n = 0
        async for raw in ws:
            n += 1
            ts = _fmt_ts()
            if raw is None:
                print(f"[{ts}] #{n} <none>", flush=True)
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            stripped = raw.strip()
            if not stripped:
                print(f"[{ts}] #{n} <empty>", flush=True)
                continue
            try:
                parsed = json.loads(stripped)
                pretty = json.dumps(parsed, indent=2, sort_keys=True)
                print(f"[{ts}] #{n} (json, {len(stripped)}B):\n{pretty}", flush=True)
            except Exception:
                print(f"[{ts}] #{n} (raw, {len(stripped)}B): {stripped}", flush=True)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
