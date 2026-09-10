# Prompt 5 — Cheap asymmetric bets (analysis, then confirm-gated)

Analysis first. Place nothing until I reply "confirm". Concise. Start with today's UTC date.

---

Using the `trading` MCP, build me a cheap-bet slate on Polymarket for a **$BANKROLL** bankroll.
Analysis first — no orders until I confirm.

1. **SCREEN** — `polymarket_scan_cheap_longshots(max_price=$MAX_PRICE, min_liquidity=1000, limit=40)`.
   Prefer `fee_free` rows (Geopolitics: 0 taker AND 0 maker fee — on every other category a taker
   pays `rate × p × (1−p)` per share, small at a 5c entry but not zero).

2. **READ THE RULES** — for every shortlisted market, `polymarket_get_market(slug)` and quote the
   resolution clause verbatim. Reject anything whose wording could resolve against a correct thesis.
   This step is not optional: on cheap markets the wording, not the headline, is the whole trade.

3. **PRICE IT** — `polymarket_get_books` for the real ask and size (gamma's cached quote has shown
   ghosts). Then `polymarket_get_flow(condition_id, hours=168)`: a large one-sided entry without
   public news is a follow-signal; a dump against the side I want is a stay-out.
   `polymarket_get_price_history(token_id, interval="1m")` for where this has traded.

4. **STATE THE CASE HONESTLY** — for each candidate, one line on why the market's price is wrong.
   If I don't have one, say so and drop it. A 20x payoff at 5c is the market saying 5%, and it is
   usually right. I want the two or three where there is an actual argument, not the 40 cheapest.

5. **SLATE** — table: market | outcome | price | payoff multiple | stake | max loss | fee_free |
   holding_rewards | resolution date | the argument in one line.
   Size so total stake ≤ bankroll and no single bet exceeds ~20% of it. These are lottery tickets:
   expect most to expire worthless, and say that in the summary rather than implying a portfolio EV.

6. **ON "confirm"** — place with `polymarket_place_order(execution="maker")` resting at or below the
   named price. Maker-only: it costs zero fee and there is no hurry on a market resolving in months.
   Only use `execution="taker"` if I explicitly ask. Report fills via `polymarket_get_positions()`.

Note: `holding_rewards` marks markets the venue flags as holding-reward eligible. The mechanism is
UNDOCUMENTED as of 2026-09-08 — report the flag, do not assume it pays, and do not price it into
the case for a bet.
