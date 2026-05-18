---
name: trading-mcp-profit-maximization-2026-05-14
description: trading-mcp expanded from 44 → 68 tools — full Hyperliquid module + cross-venue aggregator (yield/borrow/funding/NAV/screener/promotions). Bybit + OKX drafted then removed at user request.
metadata:
  type: project
---

# trading-mcp profit-maximization sprint — shipped 2026-05-14

> **Update later 2026-05-14:** User said "we don't need OKX and Bybit for now."
> Bybit (`exchanges/bybit.py`) and OKX (`exchanges/okx.py`) modules were
> deleted; `aggregator.py`, `server.py`, `.env.example`, and `README.md`
> trimmed to the remaining four venues. Container rebuilds clean. Final
> tool inventory: **68** (Binance 33 / Kraken 6 / HL 18 / WhiteBIT 5 /
> Aggregator 6). Re-adding Bybit/OKX later: this memory's "What shipped"
> section preserves the implementation map (V5 signing pattern, endpoint
> paths, tool surface) — start from there rather than reconstructing.

Built on top of [[trading-mcp-earn-discovery-2026-05-14]] (which added Kraken + WhiteBIT + Binance promotions). This sprint targets *decision* tools — "where should I park / borrow / carry?" — rather than just per-venue read/write.

## What shipped

**Hyperliquid** (`exchanges/hyperliquid.py`, 18 tools, was 0/stub):
- Read: `_get_meta`, `_get_spot_meta`, `_get_all_mids`, `_get_funding_rates` (auto-annualized, sorted), `_get_funding_history`, `_get_perp_account`, `_get_spot_balances`, `_get_open_orders`, `_get_fills`, `_get_user_funding_payments`, `_get_vault_equities`, `_get_hlp_summary`.
- Trade: `_place_perp_order` (limit/market + tif), `_market_close_position`, `_cancel_perp_order`, `_set_leverage`.
- Transfer: `_bridge_usdc` (perp↔spot), `_vault_transfer` (HLP default, dry-run unless `confirm=True`), `_withdraw_usdc` (dry-run unless `confirm=True`).
- Discovery: `_find_best_funding_rates(top_n, side)` — short carry vs long carry.
- Uses `hyperliquid-python-sdk>=0.9.0` + `eth-account>=0.11.0`. Constants: `HLP_VAULT_ADDRESS = 0xdfc24b077bc1425ad1dea75bcb6f8158e10df303`. HL funding intervals are **hourly** (not 8h) — annualized as `hourly * 24 * 365`. Container build pulled SDK 0.23.0.

**Bybit** (`exchanges/bybit.py`, 13 tools, new):
- V5 API, HMAC-SHA256 over `timestamp + api_key + recv_window + payload`.
- Balances/orders/leverage; perp tickers + funding history; `_find_best_funding_rates` (8h interval); Earn FlexibleSaving products + best-rate ranker + active positions; `_list_promotions` from `/v5/announcements/index`.

**OKX** (`exchanges/okx.py`, 16 tools, new):
- V5 API, HMAC-SHA256 (base64) of `timestamp + method + path + body`. Requires passphrase (`OKX_API_PASSPHRASE`). Testnet routed via `x-simulated-trading: 1` header.
- Trading + funding + flexible savings + staking/DeFi offers (`/api/v5/finance/staking-defi/offers`) + `_find_best_funding_rates` (uses `instId=ANY` shorthand) + signed `_list_announcements`.

**Cross-venue aggregator** (`exchanges/aggregator.py`, 6 tools, new — Bybit/OKX branches removed in trim):
- `find_best_yield_anywhere(asset, top_n)` — merges Binance Simple Earn (flex+lock), Kraken Earn, HL HLP. Each venue `_safe()`-wrapped. Kraken rates normalized (they ship as percent, others as decimals).
- `find_cheapest_borrow(asset)` — Binance `get_margin_interest_rate_history` only after trim (Bybit/OKX branches removed). Kept as aggregator shape so re-adding later is one branch each.
- `compare_perp_funding(coin)` — HL hourly + Binance USDⓈ-M 8h. Reports max APR spread + carry hint.
- `get_total_nav(idle_threshold_usd)` — USD roll-up across Binance / Kraken / WhiteBIT / HL. Non-stable assets priced via Binance USDT spot; unpriced assets listed separately. Flags stablecoin balances ≥ threshold sitting outside Earn locations.
- `funding_carry_screener(top_n, min_oi_usd)` — HL perp universe, score = `|funding_apr| × min(1, oi_usd/$50M)`, filter `min_oi_usd` (default $5M). Feeder for [[funding-carry-auto-sizing-multiasset-2026-05-13]] basket expansion.
- `find_best_promotions(keywords)` — Binance CMS only after trim.

**Reference for Bybit/OKX re-add** (deleted modules but pattern preserved here for restoration):
- *Bybit V5*: HMAC-SHA256 over `timestamp + api_key + recv_window + payload`; headers `X-BAPI-*`. Endpoints: `/v5/account/wallet-balance`, `/v5/position/list`, `/v5/order/create`, `/v5/order/cancel`, `/v5/market/tickers` (has `fundingRate`), `/v5/market/funding/history`, `/v5/earn/product?category=FlexibleSaving`, `/v5/earn/position`, `/v5/announcements/index?locale=en-US`, `/v5/spot-margin-trade/collateral-info?currency=` (hourlyBorrowRate).
- *OKX V5*: HMAC-SHA256 base64 of `timestamp + method + path + body`; ISO-8601 ms timestamp with `Z`; passphrase header `OK-ACCESS-PASSPHRASE`; testnet via `x-simulated-trading: 1`. Endpoints: `/api/v5/account/balance`, `/api/v5/account/positions`, `/api/v5/trade/order`, `/api/v5/trade/cancel-order`, `/api/v5/public/funding-rate?instId=ANY` (batch), `/api/v5/finance/savings/lending-rate-summary`, `/api/v5/finance/staking-defi/offers`, `/api/v5/support/announcements`, `/api/v5/account/interest-rate?ccy=`. Bybit funds 8h (×3×365 APR); OKX funds 8h too.

## What was rejected / not in scope

- **Binance public Launchpool/Megadrop signed endpoints** — already covered by `binance_list_promotions` from CMS. Skipped.
- **Kraken margin borrow rates in `find_cheapest_borrow`** — Kraken's borrow rate isn't exposed in a stable REST endpoint; left out of the comparator.
- **Per-venue WS streams** — outside MCP scope (MCP is request/response).
- **WhiteBIT Earn/yield discovery** — already established (see [[trading-mcp-earn-discovery-2026-05-14]]) that WhiteBIT Smart Staking has no REST API. Aggregator skips it for `find_best_yield_anywhere`.
- **30-day funding history in `funding_carry_screener`** — would require 30 × N HTTP calls. Used current funding × OI heuristic as cheaper proxy. Operator should still call `hyperliquid_get_funding_history` per top candidate before committing.

## Build / deploy verification

```
docker compose up -d --build
```
After the trim, container starts cleanly with current `.env` (Binance + Kraken + WhiteBIT keys present, HL empty). Startup log confirmed:
```
Registered 33 tools from … binance
Registered 6  tools from … kraken
Skipped     … hyperliquid (no creds)
Registered 5  tools from … whitebit
Registered 6  tools from … aggregator
```
**Active today: 50 tools. Full surface once HL keys land: 68.**

## Untested (verify on first live run)

- **Hyperliquid** SDK methods `query_vault_details`, `user_funding_history`, `user_vault_equities` — SDK 0.23.0 exposes these but names may have drifted; aggregator's HLP-APR enrichment is wrapped in try/except.
- **`get_total_nav` pricing fallback** — coins without a USDT pair on Binance go into `unpriced` rather than estimated.

## Startup validation (added 2026-05-14)

Each exchange module exposes `validate()` — a cheap authed call run from `server._register_all` after a successful `register()`. Failures log WARNING and surface in the `Startup summary:` block but do **not** unregister tools or crash the server. Validators in use:

- Binance: `client.get_account()` — verifies key/secret/IP/Read perm in one shot.
- Kraken: signed `/0/private/Balance` — catches HMAC / nonce / perm.
- WhiteBIT: signed `/api/v4/main-account/balance` — catches `nonceWindow` / sig / scope.
- Hyperliquid: 3-layer — (1) `user_state(master)` resolves, (2) eth_account derives agent, (3) `/info` `extraAgents` lists agent on master. If `HYPERLIQUID_VAULT_ADDRESS` is set, also verifies it via `/info` `subAccounts` and that it's owned by the master.

## Hyperliquid sub-account routing (added 2026-05-14)

`HYPERLIQUID_ACCOUNT_ADDRESS` always holds the **master** (the wallet that approved the agent). Optional `HYPERLIQUID_VAULT_ADDRESS` routes reads + signed trades to a sub-account: master's agent signs, payload includes `vaultAddress=<sub>`, HL executes on the sub. No separate agent approval on the sub. Verified live: user's master is near-empty (dust); funds sit in subs; validation correctly shows master agent + sub balance side-by-side. Implementation: `_master_address()`, `_vault_address()`, `_target_address()` helpers in `hyperliquid.py`; `Exchange(wallet, base, account_address=master, vault_address=vault)`.

## Why: How to apply (additions)

- Always set `HYPERLIQUID_ACCOUNT_ADDRESS` to the master. Use `HYPERLIQUID_VAULT_ADDRESS` to target a sub — never swap the master for a sub directly (the agent isn't approved there).
- When a future tool needs *per-call* vault selection (e.g. iterating subs for consolidation), add a `vault_address: str | None = None` parameter to the tool and pass it through to a one-shot `Exchange(..., vault_address=…)` instance instead of the cached `_exchange()` singleton.

## Why: How to apply

- **Daily "where's the money sitting?" check** → `get_total_nav()`. Idle list directly tells you what to move.
- **Before deploying capital to Earn** → `find_best_yield_anywhere(asset)` instead of calling each `*_find_best_*_rates` individually.
- **Funding-carry basket evaluation** → `funding_carry_screener()` for candidates, then `compare_perp_funding(coin)` per pick to confirm cross-venue spread is real. Feed survivors into the funding-carry bot config (see [[funding-carry-auto-sizing-multiasset-2026-05-13]]).
- **Margin / basis trade pre-trade** → `find_cheapest_borrow(asset)` before opening the borrow leg.
- **Weekly promotions scan** → `find_best_promotions(keywords=["launchpool", "megadrop", "jumpstart", "airdrop", "competition"])`. Pair with `/schedule` once a routine is wanted.
- **HLP deposit/redeem** → `hyperliquid_vault_transfer` (always dry-run first; HLP has 4-day withdraw lock from most recent deposit).

## Next-cycle ideas (not built)

1. Schedule a daily `get_total_nav` + `find_best_promotions` digest via `/schedule`.
2. Add a `route_order(coin, amount, side)` aggregator that pre-checks best execution venue by spread×fee×depth — Bybit `tickers` + Binance `book_ticker` + OKX `tickers`.
3. Add Hyperliquid spot orders + spot bridge (currently only perp trading is wired).
4. Extend `find_cheapest_borrow` to include Kraken once a stable rate endpoint surfaces.

Related: [[trading-mcp-earn-discovery-2026-05-14]] for the prior layer (Earn discovery), [[project-binance-mcp-2026-05-13]] for the original MCP architecture, [[funding-carry-auto-sizing-multiasset-2026-05-13]] for the bot the screener feeds.
