# Prompt 4 — Farm a liquidity-reward pool (EXECUTES, confirm-gated)

Dry-run first. Place nothing until I reply "confirm". Concise: table, then the exact orders you
would place. Start with today's UTC date.

---

Using the `trading` MCP, arm ONE liquidity-reward pool on Polymarket. Dry-run first.

**Target selection**
1. `polymarket_scan_reward_pools(limit=25, max_capital=$MAX_PER_MARKET)`.
2. Pick the single best row by `est_daily_usd`, subject to ALL of:
   - `competition_shares` == 0, or my `min_size` ≥ 25% of current competition;
   - `est_daily_usd` ≥ $1.50 (the payout floor is $1/day);
   - `end` is ≥ 7 days out (a market resolving sooner isn't worth the setup);
   - I can afford `capital_usd`.
3. `polymarket_get_clob_market_info(condition_id)` — take tick size, min order size and the LIVE
   rewards config from here, not from the scan (gamma's copy lags).
4. `polymarket_get_market(slug)` — read the description. If resolution is ambiguous, pick the next row.
5. `polymarket_get_price_history(token_id, interval="1w")` — if `vol_per_point` is large relative to
   `max_spread_c`, the quote will be run over before it accrues. Say so and pick the next row.

**Quote construction**
- Read the real book with `polymarket_get_books([yes_token, no_token])`.
- Midpoint = (best bid + best ask)/2 of the YES token.
- Post TWO orders, both `execution="maker"` (post-only — the exchange rejects anything that would
  cross, which is a hard maker guarantee: zero fee, and eligible for rewards):
  - BUY `min_size` YES at the tick just inside `midpoint − max_spread_c`;
  - BUY `min_size` NO  at the tick just inside `(1 − midpoint) − max_spread_c`.
  Two BUYs, one on each token — that is what makes the quote two-sided without holding inventory.
- Size at `min_size` EXACTLY. Not larger. On a wide book the midpoint is uninformative, and the
  minimum caps a pickoff at a few dollars against the pool. Size is not the lever here; being the
  only qualifying maker is.

**Dry-run output** — a table: market | pool $/day | my est $/day | the 2 orders (token, side, price,
size, $) | total capital | worst-case loss if both fills go against me | end date. Then STOP.

**On "confirm"** — place both with `polymarket_place_order(execution="maker")`. Then immediately:
- `polymarket_get_open_orders()` — confirm both are resting;
- `polymarket_check_order_scoring(order_id)` on each — an order can be live and still score nothing;
- `polymarket_get_reward_percentages()` — confirm a non-zero share on this market.
Report all three. If scoring is false or the share is 0%, say so plainly and diagnose (too small,
too far from mid, or one-sided outside [0.10, 0.90]) — do not leave a non-scoring quote resting.

**Follow-up (run daily)** — `polymarket_get_rewards(days=7)` for actual paid rewards, plus
`polymarket_get_positions()` to catch fills. Compare paid vs `est_daily_usd`. If competition arrived
and my share collapsed, say REROTATE and name the next target.
