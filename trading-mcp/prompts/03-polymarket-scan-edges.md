# Prompt 3 — Polymarket edge scan (READ-ONLY)

Read-only. Place nothing. Be concise: verdict first, a table, no narration. Start with today's UTC date.

---

Using the `trading` MCP, scan Polymarket for executable edges. READ-ONLY — place no orders.
Date header, tables, one-line verdict per lane. No filler.

1. **REWARD POOLS** — `polymarket_scan_reward_pools(limit=25, max_capital=<my max per market>)`.
   This reads REAL books, not gamma's cached quotes. Rank by `est_daily_usd`.
   Drop any row where:
   - `est_daily_usd` < 1.50 — the payout floor is $1/day and the estimate assumes the band stays empty.
   - `spread` > ~0.10 — a wide book means the midpoint is uninformative and quoting inside it is
     an invitation to be picked off. Quote these ONLY at `min_size`, never larger.
   For survivors report: pool, competition, capital, est $/day, spread, end date.

2. **NEG-RISK** — `polymarket_scan_negrisk(limit=10)`.
   Report ONLY `sell_field_net_edge > 0`. Ignore `sum_ask < 1` entirely — that is an incomplete
   outcome set (augmented neg-risk carries unnamed placeholders + "Other"), NOT an arb. As of
   2026-09-08 the whole venue was net-negative (best −0.0014); a positive row is news, so
   re-verify it with `polymarket_get_books` on every leg before believing it.

3. **COMBOS** — `polymarket_get_combo_markets(limit=5)`. Report `rfq_live` only. If it is still
   false, one line: "combos not executable". Do not analyze the catalog.

4. **CHEAP BETS** — `polymarket_scan_cheap_longshots(max_price=0.10, min_liquidity=1000)`.
   Flag `fee_free` (Geopolitics — 0 taker AND 0 maker fee) and `holding_rewards` rows separately.
   For any candidate you would actually name, first call `polymarket_get_market(slug)` and read the
   DESCRIPTION — resolution wording, not the headline, decides these. Say explicitly when a
   20x payoff at 5c is simply the market pricing 5% and you have no reason to disagree.

5. **VERDICT** — one table: lane | best opportunity | capital | est $/day | main risk | GO/NO-GO.
   End with the single recommended next action. If nothing clears, say NOTHING CLEARS — that is a
   valid and frequent answer.

Standing facts (do not re-derive):
- Fee = `rate × p × (1−p)` per share, taker only; makers pay 0. Crypto 0.07, Sports 0.05,
  Politics/Finance/Tech 0.04, Economics/Culture/Weather/Other 0.05, **Geopolitics 0**.
- Liquidity rewards score only orders ≥ `rewardsMinSize` within `rewardsMaxSpread` of the midpoint,
  resting ≥3.5 s. Single-sided scores at 1/3 only while mid ∈ [0.10, 0.90]; outside that, two-sided
  is mandatory. A sole qualifying maker takes the whole pool.
- Never quote availability from gamma's `bestBid`/`bestAsk` — they have shown ghost quotes.
  Every claim about what is on the book comes from `polymarket_get_books`.
