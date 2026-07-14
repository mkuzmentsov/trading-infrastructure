# Execution-latency baseline — Hetzner Helsinki, 2026-07-14

Measured in-cluster from the `sol-fav` pod (`latency_probe.py`, raw:
`baseline_hel_2026-07-14.json`). Purpose: before/after comparison for the
fast-execution-client work and the US-node A/B.

## Network layer (medians unless noted)

| path | cold (new conn) | warm (keep-alive) |
|---|---|---|
| CLOB REST `/price` | 227ms (dns 101 + tls 30 + ttfb 95) | **50ms** |
| CLOB REST POST `/order` (reject proxy) | 239ms (ttfb 98) | ~100ms est. |
| gamma REST | — | 15ms (edge-cached) |
| Binance REST ticker/klines (`api` + `vision`) | 469ms | **257ms** |
| Binance WS aggTrade delivery (T vs arrival) | — | 156ms (p90 160, max 388) |
| CLOB market WS delivery (server ts vs arrival) | connect 264ms | **26ms** (p90 52) |
| RTDS WS crypto_prices delivery | connect 318ms | **542ms** (!) |

Clock caveat: node clock measured −77ms vs Binance serverTime (midpoint
method) — Binance WS true delivery may be ~230ms; CLOB WS uses PM's clock
(offset unknown). Relative before/after comparisons are unaffected.

**Geography surprise:** CLOB origin is ~25ms one-way from Helsinki → it is in
**Europe**, not US East (edge colo HEL, warm TTFB 50ms, WS delivery 26ms).
A US node would likely *worsen* the order leg while improving the Binance
(Tokyo) leg — net roughly a wash by these numbers. The US A/B test remains
worthwhile but the expected win is small; the software layer is where the
seconds are.

## CPU layer

- EIP-712 order signing (py_clob_client_v2, warm): **9.6ms** median.
- FIRST `create_order` per token: **298ms** (tick-size/neg-risk REST lookups,
  then cached). fav/mom bots pay this on every bar (fresh token each bar)
  unless the cache is pre-warmed at bar start.

## Application layer (the real problem)

**fav_taker / mom bots (current code)**: 3s polling loop; each evaluation is a
*sequential* REST chain measured at **~1.15s**:
klines 417ms + spot ticker 417ms + gamma 130ms + CLOB `/price` 167ms.
Signal age at decision ≈ poll wait (0–3s, avg 1.5s) + chain 1.15s + spot RTT/2
≈ **2–4.5s** from Binance move to order submission, plus first-order signing
298ms + POST ~240ms cold.

**maker engine (lock bots)**: already WS-fed (CLOB book 26ms, Binance 156ms)
but timer-driven at `EVAL_INTERVAL_MS=200` and RTDS (542ms stale) for the
bracket symbol; signs on trigger (first-per-token 298ms) on a cold-ish session.

## Where the improvements land (predicted)

| fix | fav/mom saving | maker saving |
|---|---|---|
| event-driven on Binance WS tick (drop 3s poll + REST chain) | **~2–4s** | ~100ms (drop 200ms tick) |
| CLOB WS book instead of REST `/price` polls | ~1.5s staleness → 26ms | already has |
| pre-sign + pre-warm tick-size cache at bar start | ~300ms on the bet | ~300ms on first order |
| persistent warm session to CLOB | ~140ms/POST | ~140ms/POST |

Target after rework: Binance-move → order-on-wire ≈ **250–400ms** (dominated
by Binance Tokyo delivery 156–230ms + POST 50–100ms), vs ~2.5–5s today —
about a **10× improvement**, all software, no new infra.

## US node A/B (Hetzner Ashburn cpx11, 2026-07-14) — NO-GO

Throwaway probe VM 178.156.197.152 (created + destroyed same hour):

| endpoint from US-East | result |
|---|---|
| Binance `api.binance.com` REST + WS | **HTTP 451 geo-blocked** |
| `data-api/-stream.binance.vision` (public data mirror) | works; WS delivery no better than Helsinki after clock correction |
| CLOB GET `/time` | 107ms — WORSE than Helsinki (50ms warm); origin is EU |
| CLOB **POST `/order`** | **HTTP 403 Forbidden** (Helsinki same request: 401 Unauthorized) → Cloudflare geo-block on the trading endpoint for US IPs |

Conclusion: a US worker **cannot place Polymarket orders** (403 geo-block) and
**cannot read Binance's main feed** (451), while the CLOB origin is in Europe
anyway — Helsinki is already near-optimal placement. US node idea closed;
if we ever want to shave the signal leg, the candidate is an EU-West node
(London ≈ Tokyo→London one-way ~110ms + ~15ms to CLOB), worth ~30-40ms at
most vs Helsinki.

## Germany check (existing nbg1 k3s worker, 2026-07-14) — also NO-GO

| from Nuremberg | result | Helsinki |
|---|---|---|
| Binance REST | OK, warm 235ms | 257ms |
| Binance WS delivery | 141ms median | 156ms |
| CLOB GET warm | **31ms** | 50ms |
| CLOB **POST `/order`** | **403 Forbidden** (geo-block) | 401 (reaches API) |

Germany would save only **~25ms total** (signal −15ms, order −10ms one-way) —
and trading is geo-blocked anyway. Bonus finding: 31ms warm RTT from
Nuremberg pins the CLOB origin to ~Frankfurt. The origin sits in a country
Polymarket itself geo-blocks; nearest non-blocked candidates to FRA are
Zurich/Vienna/Prague (~10-15ms away) — max ~20ms better than Helsinki,
pending their own geo-block probes. Helsinki stays.
