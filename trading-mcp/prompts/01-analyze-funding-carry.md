# Prompt 1 — Analyze (READ-ONLY)

Read-only. No orders/transfers/earn changes. Be concise: lead with the verdict, use a table,
skip narration. Start with today's UTC date.

---

Using the `trading` MCP, analyze my funding-carry book. READ-ONLY — place nothing. Be short:
date header, a table, a one-line verdict. No filler.

1. STATE — funding_carry_status + get_total_nav. List each open carry (short venue/coin/size/
   funding, long spot venue/size, earn alloc) and idle stables per venue. Cross-check via
   hyperliquid_get_perp_account, kraken_futures_get_open_positions, binance_get_futures_positions,
   kraken_get_balances, binance_get_spot_balances, whitebit_get_main_balance, and earn positions
   (kraken_list_earn_allocations, binance_get_earn_flexible_positions, whitebit_get_lending_investments).

2. ECONOMICS — per carry: effective APR = short funding + long-leg earn (flex or short-bonded)
   − fees. Report delta (|spot−perp|/perp), liq room, and realized PnL (funding + earn − fees).

3. SCAN best COMBINED (funding + long-leg earn):
   - Short: compare_perp_funding(coin) for held coin + top funding_carry_screener names
     (HL / Binance / Kraken Futures).
   - Long-leg earn on the COIN: find_best_yield_anywhere(asset=COIN) +
     kraken_find_best_earn_rates(asset=COIN) + binance_list_earn_locked_offers. WhiteBIT is
     NOT in find_best_yield_anywhere — query whitebit_list_lending_plans directly. Prefer flex;
     bonded only if lock ≤ ~14d AND it clearly beats flex.
   - EARN SANITY (Kraken apr_estimate is unreliable — it has reported phantom 10–15% on BTC
     when the real rate was 2.1%): only credit a rate where can_allocate=true; treat it as an
     ESTIMATE. For non-stable / non-PoS assets (BTC, etc.) any earn >5% is SUSPECT — verify
     against the venue app before crediting, else use a conservative floor (~2%) or 0. Never
     feed an unverified high earn rate into the go/no-go.

4. VERDICT — HOLD or SWITCH. Switch only if (best − current) over 30d beats round-trip cost
   (unwind + transfer + reopen fees + lock). One table: current eff APR | best candidate |
   Δ | switch cost | breakeven days | verdict. End with the single recommended action.
