---
name: PM maker-rebate roadmap (parked)
description: Polymarket pays maker rebates (20% of taker fees on crypto, daily payout, $1 USDC min). Researched 2026-05-08 and deferred — current 0.99 exit-skim usage earns rounding-error rebates.
type: project
---

**Status:** parked — revisit only if we build a dedicated mid-price market-making strategy.

**Polymarket fee/rebate structure (per https://docs.polymarket.com/market-makers/maker-rebates):**

- Taker fees on crypto markets: `fee = C × 0.07 × p × (1−p)` (C = shares, p = price)
- Maker rebate: 20% of taker-fee pool on crypto, redistributed daily by maker contribution
- Min payout: $1 USDC accrued
- Geopolitics is fee-free (no rebate)

**Why parked:**

`p × (1−p)` collapses near edges → at p=0.99 the per-trade fee pool is $0.023 on a $33 fill, so max rebate is ~$0.005/trade even alone in the pool. The user's 0.99 limit-sell experiment (8.9h bundle, trades 5+6) earned <$0.01 combined. Zero meaningful upside on the *exit* side; just adds tail-risk vs the bot's existing FAK skim.

**Why a real rebate strategy would be valuable:**

At p=0.50 the same trade generates $0.117 rebate — 25× more per filled dollar. A real edge requires posting resting orders at p=0.40-0.60 across markets and harvesting. That's a market-making strategy, separate from the directional latency-arb bot. Inventory risk on whichever side fills.

**How to apply:**

- Don't pursue maker rebates as a tweak to the current 1h bot exits; the math doesn't work at 0.99.
- If we ever build a separate market-making strategy on PM crypto markets, this is where to look — and the eligibility/payout mechanics are documented at the link above.
- Pre-check before resurrecting: scan the bundle corpus for ticks where p ∈ [0.40, 0.60] AND maker depth on either side is thin enough that a posted limit would clear (i.e., real fill probability, not just notional rebate).