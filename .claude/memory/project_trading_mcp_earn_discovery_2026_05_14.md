---
name: trading-mcp-earn-discovery-2026-05-14
description: trading-mcp gained promotion + Earn discovery across Binance/Kraken/WhiteBIT (46 tools total). Hyperliquid still stub.
metadata:
  type: project
---

# trading-mcp Earn / promotions discovery — shipped 2026-05-14

Replaced the Kraken and WhiteBIT stubs (returned 0 tools regardless of creds) with read-only Earn coverage, and added a public Binance announcements scraper. Goal: let Claude Desktop scan all configured exchanges for new investment opportunities (competitions, airdrops, Launchpool, Earn yield) on demand.

## What shipped

**Binance** (`exchanges/binance.py`, now 33 tools — up from 32):
- `binance_list_promotions(category, keywords, limit)` — hits the public CMS endpoint `https://www.binance.com/bapi/composite/v1/public/cms/article/list/query`. Categories map to catalog IDs: activities=93, new-listings=48, news=49, delisting=161. No auth. Filters by case-insensitive keyword substring on title. Returns title / releaseDate / URL.

**Kraken** (`exchanges/kraken.py`, 6 tools, was 0/stub):
- Signed REST client (HMAC-SHA512, base64-decoded secret, nonce in ms).
- `kraken_get_balances`, `kraken_get_balances_ex`
- `kraken_list_earn_strategies(asset, lock_type, limit≤64)` — `/0/private/Earn/Strategies`
- `kraken_list_earn_allocations` — `/0/private/Earn/Allocations`
- `kraken_get_earn_allocation_status(strategy_id)`
- `kraken_find_best_earn_rates(asset, top_n)` — ranks by `apr_estimate.high`

**WhiteBIT** (`exchanges/whitebit.py`, 7 tools, was 0/stub):
- Signed JSON client (X-TXC-APIKEY / X-TXC-PAYLOAD / X-TXC-SIGNATURE, base64+HMAC-SHA512).
- `whitebit_get_main_balance`, `whitebit_get_trade_balance`, `whitebit_get_collateral_balance`
- `whitebit_list_smart_staking_plans` — public `/api/v4/public/smart-staking`
- `whitebit_get_smart_staking_active`, `whitebit_get_smart_staking_history`
- `whitebit_find_best_smart_staking_rates(asset, top_n)` — ranks public plans by APR

No subscribe/withdraw/allocate verbs — read-only by design. New deps: none (httpx already present).

## What was rejected

- Hyperliquid impl: out of scope (no creds in `.env` anyway).
- Pulling Binance Launchpool/Megadrop via signed API: those endpoints are inconsistent and `binance_list_promotions` already surfaces the same content via the announcements stream.

## Open verification items (test against live accounts on first run)

- **Kraken Earn** requires the API key to have the "Query Earn" permission enabled at kraken.com/u/security/api. Without it the call returns `EAPI:Invalid permissions`.

## Fixes after first live run (2026-05-14)

Three bugs surfaced on the first end-to-end run and were fixed:

1. **Binance `binance_list_promotions` returned []** — response shape is `data.catalogs[0].articles`, not `data.articles`. Parser now tries both. Added `User-Agent: Mozilla/5.0 trading-mcp` header (some Binance edge nodes 451 unknown UAs).
2. **WhiteBIT `Invalid payload` 400** — sending `nonceWindow: true` requires the API key to have the nonce-window option enabled; without it, every signed call 400s. Default is now to omit `nonceWindow` entirely. Also switched to compact JSON (`separators=(',',':')`) for byte-identical signature/body match.
3. **WhiteBIT Smart Staking has no REST API.** Probed all plausible paths (`/api/v4/public/smart-staking`, `…/smart-staking/plans`, `…/main-account/smart-staking/*`, `…/staking`, `…/savings/*`, `…/earn/*`) — every one returned 404. WhiteBIT's Smart Staking is **web-only**. Removed all smart-staking tools; replaced with `whitebit_smart_staking_info` that returns the browse URL `https://whitebit.com/staking`. WhiteBIT tool count: 7 → 5.

## Final tool inventory

- Binance: 33 (incl. `binance_list_promotions`)
- Kraken: 6 (Earn read-only + balances)
- WhiteBIT: 5 (balances, fee schedule, smart-staking-info link-out)
- Hyperliquid: 0 (no creds)

**Total: 44 tools**

## Why: How to apply

- For investment-opportunity prompts, prefer the ranking tools (`*_find_best_*_rates`) + `binance_list_promotions`.
- For WhiteBIT Smart Staking, route the user to the web UI — there is no API alternative. Don't waste cycles probing for new endpoints unless WhiteBIT announces an API.
- WhiteBIT signed calls: never re-add `nonceWindow` to the default body — it requires a per-key opt-in that this account lacks.

## Why: How to apply

- When the user asks about investment opportunities, yields, or promotions: prefer the new ranking tools (`*_find_best_*_rates`) over dumping raw catalogs.
- When `*_list_promotions` or WhiteBIT smart-staking endpoints fail with 404 or unexpected JSON, the endpoint convention has shifted upstream — re-check the public API docs rather than retrying.

Related: [[trading-mcp-claude-desktop-setup-2026-05-14]] for how this gets wired into Claude Desktop and scheduled.
