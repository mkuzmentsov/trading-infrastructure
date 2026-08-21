# Commons — what the shared modules do (winner-vacuum + pm-common)

Updated 2026-08-13. Every bot in `winner-vacuum/` is `src/<bot>.py` + these
shared modules, bundled by `deploy.sh` (rsync src/ → chart/files/scripts/,
helm upgrade; **helm without the rsync ships env only, NOT code** — verify a
deploy landed with `kubectl exec ... grep <marker> /app/scripts/<bot>.py`).

## src/config.py
All env-driven knobs. Key ones: `BAR_SECONDS` (300/900/3600/14400/86400 —
selects series + slug format), `PAPER_MODE`/`DRY_RUN`/`LIVE_TRADING`
(live = LIVE_TRADING && !DRY_RUN), `LIVE_MAX_DAILY_LOSS_USD`,
`LIVE_MAX_ORDER_USD`, PM_MM_* (poolfarm), PM_TE_* (twapedge), PM_Z_*/PM_VOL_*
(mintsalvage), creds (POLYMARKET_PK/FUNDER/API_*, SIGNATURE_TYPE=2 → orders
signed by signer EOA, funded by the proxy/funder wallet).

## src/core/
- `gamma.py` — market discovery: `window_slug(ws)` builds the per-series slug
  (5m/15m: `{coin}-updown-{n}m-{ts}`; 1h: ET-name
  `{fullname}-up-or-down-{month}-{d}-{yyyy}-{h}{am/pm}-et`; 4h: `4h-{ts}`;
  1d: name-based noon-ET). `grid_window_start(now)` epoch-aligned bar start
  (noon-ET anchor for 1d). Gamma queries for CLOSED markets need
  `&closed=true`. Gamma 403s without a browser User-Agent header.
- `rtds.py` — Polymarket RTDS WS client (`wss://ws-live-data.polymarket.com`),
  topics `crypto_prices_chainlink` / `crypto_prices_twap_thirty` / `_sixty`.
  Subscribe WITHOUT `filters` (filters silently kill the stream). Values may
  be int192-scaled (`v/1e18` when v>1e12). `twap_at(sym, ts)` exact tick;
  `window_mean(sym, lo, hi)` forward-filled window mean. Relay p50 ~1.6s.
- `pm_ws.py` — CLOB market WS (book BBO/size per token, prints, heartbeats;
  `pm_state.token_id_up/_down`, `market_end_ts`).
- `binance_ws.py` / `btc_ws.py` / `agg_ws.py` — spot feeds (aggTrade) for
  lead signals.
- `positions.py` — data-api positions/redeemables helpers.
- `telegram.py` — alerts (optional).

## src/engine/
- `clob.py` — CLOB client factory (py_clob_client_v2; v2 renamed
  create_or_derive_api_creds → `create_or_derive_api_key`). `place_bet`
  (GTC post-only maker), FAK marketable orders, `cancel_order`,
  `fetch_order_status`, `get_balance_allowance` (COLLATERAL view lags tens of
  $ vs on-chain; the "balance/allowance not enough" storm = collateral truly
  consumed, restart does NOT fix). Venue rules learned live: FAK needs a
  resting match (1-tick buffer), maker $ amounts max 2 decimals (integer
  shares), marketable BUY ≥ $1, min order 5 shares, price ticks $0.01.
- `live_book.py` / `paper_book.py` — same interface; paper simulates fills
  when prints/book cross the quote (NO real orders on the venue book, and
  paper underestimates fills vs real queue position — measured 2026-08-13:
  live filled in minutes where paper sat 2.5h at zero).
- `user_ws.py` — authed user channel (fills/trades stream, balance deltas).
- `redemptions.py` + `src/sweeper.py` — post-resolution redemption; sweeper
  also does **mergePositions through the pUSD CtfCollateralAdapter** ($220
  recovered this way). PM auto-redeems resolved crypto-market winners even
  with our pods down (observed 2026-08-13).
- `relayer.py` — on-chain tx path (mint/split, merge, redeem; gas + shared
  nonce management).

## MINT / MERGE (the capability that was wrongly believed missing)
Approve pUSD to the **CtfCollateralAdapter**, call `splitPosition` ON THE
ADAPTER → it converts internally and mints canonical tradeable UP+DOWN
(docs.polymarket.com/trading/ctf/split). Merge is the mirror
(`mergePositions` on the adapter, sweeper.py:182). Ran live 18h ×6 coins in
mintsalvage. The bots wallet (funder 0xdb66d896…ea24d9) does NOT need USDC.e.

## chart/ (helm)
One generic chart; per-bot values in `chart/bots/<coin>_<bot>.yaml`
(PAPER defaults). Live flags come from `--set-string` overrides at deploy
(paperMode/dryRun/liveTrading/liveMaxDailyLossUsd/liveMaxOrderUsd/...) — the
exact live values of a release: `helm get values <release> -n
every-tick-single`. `chart/templates/secret.yaml` maps Values.bot.* → env
(add a line there when adding a knob, e.g. PM_MM_BATCH_SH ← pmMmBatchSh).
Creds overlay: `every-tick-single/chart/bots/crypto.secret.yaml` (bots PM
account; scout.secret.yaml is pm-scout's — never mix). Overlays must end
`.secret.yaml` or the key gets committed.

## pm-common/ (repo top level)
`execution/` — the FAST_EXEC generic client (event-driven WS eval, presigned
orders, warm sessions; ~10× latency win) used by the taker bots. README
inside.

## Recorders (every-tick-single/, mrec family)
`multi_recorder.py` — 100ms full-state recorder per series: roles cur/post +
next1-3 (pre-open books INCLUDING `trd` prints), RES rows with win, slugs,
volume. Configs `chart/bots/<coin>_mrec[15m|1h|1d].yaml`. Raw JSONL is
COMPACT — substring prefilters must match `"trd":[[` (NO space); a
whitespace-assuming filter silently matches nothing (the 2026-08-13 pre-open
scanner bug — histogram raw before trusting any zero).

## VENUE ORDER LIMITS — what the smallest legal bet actually is (verified 2026-08-17)
Queried live on all 8 crypto 5m markets (btc eth sol xrp doge bnb hype zec) —
identical on every one:

| field | value | source |
|---|---|---|
| `orderMinSize` / `minimum_order_size` | **5 shares** | gamma market + `clob/markets/<cid>` |
| `orderPriceMinTickSize` / `minimum_tick_size` | **0.01** | same (+ `clob/tick-size?token_id=`) |
| `negRisk` | false (5m updown are NOT neg-risk) | gamma |
| fee | `crypto_fees_v2`: 0.07·p·(1−p) per share, `takerOnly:true`, `rebateRate 0.2` | gamma `feeSchedule` |
| maker/taker base fee | 1000 (bps field, superseded by feeSchedule) | clob |

**The minimum is in SHARES, not dollars** → the cheapest legal order is
`5 × lowest legal price`:
* normal regime (tick 0.01) → 5 × 0.01 = **$0.05**
* extreme regime (tick 0.001) → 5 × 0.001 = **$0.005**
* buying a 0.94-0.99 favourite → **$4.70-4.95 is the floor** (this is what
  bounds vacmaker's per-clip risk; you cannot bet $2 on a 0.99 favourite)

**Tick size is DYNAMIC per token** — measured on 24h of btc mrec quotes:
sub-cent prices appear in **13.1% of quotes ≤0.05 and 14.1% of quotes ≥0.96,
and in 0.0% of quotes between 0.10 and 0.90**; the actual sub-cent values seen
are 0.001-0.009 / 0.991-0.999 only. So the venue runs 0.01 ticks in
[0.01, 0.99] and switches that token to 0.001 inside the outermost cent
(hence the live rejection "invalid price (0.991), max: 0.99" when the switch
had not yet fired — listen for `tick_size_change`, docs confirm the CLOB
rejects any price off the *current* tick).

⚠️ **A ~$1 order-VALUE floor is asserted in our code but NOT documented.**
`twapedge.py` guards `sh < 5 or sh * px < 1.05` in 5 places ("venue minimums:
5 shares AND $1"). docs.polymarket.com/trading/place-orders documents only
`min_order_size` (shares) + tick/precision rounding — no dollar floor. Nobody
has probed below $1, so treat sub-$1 orders as UNVERIFIED: a 5sh × 0.02 =
$0.10 bet is legal by every published rule and would be silently blocked by
our own guard. Cheap way to settle it: rest 5sh at a price that cannot fill,
read the venue's response, cancel.

⚠️ **Sizing has no clamp-up to the minimum.** Every live path computes
`sh = int(min(LIVE_SIZE, LIVE_MAX_ORDER_USD / ask))` and then *drops the trade*
if `sh < 5`. So `LIVE_MAX_ORDER_USD` below `5 × ask` does not shrink the bet —
it silently stops trading the expensive band (at ask 0.99 anything under $4.95
= no orders at all). $5 is the smallest setting that still trades 0.99 asks.

## Ops traps (each cost real money/time)
- `source .dev-env-source` with a RELATIVE path from the wrong cwd silently
  retargets kubectl at a dead EKS cluster — always absolute-cd first.
- Deploys: rsync + helm (see top). Live values via `helm get values`.
- Mid-bar pod restarts reset in-memory inventory (re-buy risk) — poolfarm
  needs on-chain inventory reconcile at startup before mid-bar restarts are
  safe (still open).
- Daily log rotation gzips `logs-training-events.jsonl` per UTC day — read
  `logs-training-events.jsonl*` including .gz for cumulative stats.
- kubectl exec + zsh: `$c[...]` is subscript syntax; pass shell vars into
  in-pod python via `env VAR=...` + single-quoted code.
