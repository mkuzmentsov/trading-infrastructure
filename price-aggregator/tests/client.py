"""Tiny test client: connect to the aggregator WS and print N ticks.
Usage: python3 tests/client.py [ws://host:8080] [n=10]"""
import asyncio
import json
import sys

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8080"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10


async def main():
    async with websockets.connect(URL) as ws:
        for _ in range(N):
            msg = json.loads(await ws.recv())
            v = msg.get("venues", {}).get("binance", {})
            print(f"{msg['symbol']} price={msg['price']} bid={msg['bid']} ask={msg['ask']} "
                  f"vol_1s={msg['vol_1s']} binance_age_ms={v.get('age_ms')}")


if __name__ == "__main__":
    asyncio.run(main())
