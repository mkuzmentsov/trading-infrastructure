# price-aggregator

Standalone market-data microservice. Ingests price + volume + orderbook (BBO)
from exchange WebSockets, republishes a normalized live price feed over its own
WS to internal clients (the PM single-side paper traders). Purpose: give the PM
bots an **unlagged** BTC price to compare against the lagged Polymarket RTDS
Chainlink feed, and test whether that lag is leverageable.

Starts with **Binance only**; venue layer is N-venue-ready (`aggregator/venues/`).

## Feeds ingested (Binance)
- `@trade`      — last trade price, size, aggressor side → price + rolling volume
- `@bookTicker` — best bid/ask + sizes → orderbook top

## Client protocol (WS)
Connect to `ws://<host>:8080`. On connect you get a snapshot per symbol, then a
throttled tick (`BROADCAST_MS`, default 100ms) per symbol:

```json
{"type":"tick","symbol":"btcusdt","ts":1699999999999,"price":62800.5,
 "bid":62800.4,"ask":62800.6,"bid_sz":1.2,"ask_sz":0.8,
 "vol_1s":0.34,"vol_10s":3.1,
 "venues":{"binance":{"price":62800.5,"bid":62800.4,"ask":62800.6,"age_ms":40}}}
```
Optional filter: send `{"op":"subscribe","symbols":["btcusdt"]}`.

`GET /healthz` → 200 when a venue is fresh, else 503 (k8s probes).

## Config (env)
`SYMBOLS` (csv, lowercase, default `btcusdt`), `VENUES` (default `binance`),
`WS_PORT` (8080), `BROADCAST_MS` (100), `LOG_LEVEL` (INFO).

## Run locally (Docker)
```bash
docker compose up -d --build
python3 tests/client.py ws://localhost:8899 10   # host port 8899 -> container 8080
curl -s localhost:8899/healthz
```

## Deploy (Hetzner dev k3s)
```bash
cd <repo root> && source .dev-env-source        # KUBECONFIG for hetzner-k3s
docker buildx build --platform linux/amd64 -t mkuzmentsov/price-aggregator:0.1 --push .
kubectl apply -f k8s/deployment.yaml
kubectl -n market-data rollout status deploy/price-aggregator
```
In-cluster address for clients (e.g. the PM bots in `every-tick-single`):
`ws://price-aggregator.market-data.svc.cluster.local:8080`
