# VENUE.md — fee/subsidy mechanics on PM 5m crypto up/down
Agent: polymarket-expert. Date 2026-09-15. Scope: 5m crypto up/down only.
All numbers below are **confirmed-live** unless marked [docs-only].
Wallets: fleet proxy `0xdb66d896…24d9`, openmm `0xd632c1e1…1b2f`.

## VERDICT IN ONE LINE
**There is no reachable fee reduction and no live subsidy on 5m crypto.** The
reachable taker-tier saving is **≤ 0.09 c/share at p=0.50 and ≤ 0.010 c/share in
our actual 0.97 lane**. `holdingRewardsEnabled` is **false on 413/413** 5m crypto
bars. `clobRewards` (native *and* the newly-found **sponsored** pool) is **absent
on 364/364**. The 20% maker rebate is the only maker income and it is
**undiluted but unimprovable**. No closed cell reopens.

## ⭐ The one reframing that matters
Our measured effective fee is **0.2341 c/share**, not 1.75.
30d: 4,721 fills, 57,626 shares, $53,436 cash, $134.00 of fee — reconciled to
**$135.36 by Σ shares·0.07·p_fill·(1−p_fill), a 1.0% match** (the residual is the
0.5% of rows that were maker fills, which are fee-free).
Two consequences the strategy agents should use directly:
1. **The fee is charged on the FILL price, not the limit price.** Tested and
   closed — there is no limit-price fee arbitrage on FAK.
2. **The fee is a tax on uncertainty, not a flat tax.** Mean realised p(1−p) =
   0.0334. A strategy that trades at p≈0.5 pays **7.5× our current fee**. The
   "cost exceeds mispricing in every band" result is a statement about the
   **mid-band**, and the current lane is nowhere near it.

| p | fee c/sh | p | fee c/sh |
|---|---|---|---|
|0.50|1.750|0.95|0.333|
|0.70|1.470|0.97|0.204|
|0.80|1.120|0.99|0.069|
|0.90|0.630|0.996 (tick 0.001)|0.028|

## 1. Taker Rebate Program — real thresholds, and why it cannot help
Live table (docs/programs/taker-rebates.md, exact):

| Tier | 30d wV | Rebate | Level-up bonus |
|---|---|---|---|
|0 None|<$2,000|0%|—|
|1 Bronze|$2,000|3%|$10|
|2 Silver|$20,000|8%|$50|
|3 Gold|$200,000|18%|$250|
|4 Platinum|$1,000,000|32%|$1,500|
|5 Diamond|$4,000,000|44%|$7,500|
|6 Obsidian|$10,000,000|50%|$25,000|

`wV = TradeSize × (1−EntryPrice) × CategoryWeight`, TradeSize = shares × price,
crypto weight 2.3. **Taker fills only.**

### ⭐ The identity nobody had: wV is exactly proportional to the fee
wV = (shares·p)(1−p)·2.3 and fee = shares·0.07·p(1−p), so
**wV ≡ (2.3/0.07) × fee = 32.857 × fee**, independently of price and size.
Corollaries:
- **There is no cheap way to farm wV.** Every $1 of wV costs exactly 3.04 c of fee.
- The archive note "0.99 clips earn ~no wV" is only half true: per dollar of
  *capital* yes, per dollar of *fee* a 0.99 clip and a 0.50 clip are identical.
- A tier threshold is really a 30-day **fee-spend** threshold:
  Bronze $61, Silver $609, Gold $6,087, Platinum $30,435, Obsidian $304,348.

### Our position (confirmed live)
`GET polymarket.com/api/profile/userData?address=0xdb66…` →
**`"takerTier":1,"takerTierName":"Bronze"`**.
30d taker fees $134.00 ⇒ **30d wV ≈ $4,403**. Silver is **4.5×** away, Gold **45×**.
(The same identity predicts Bronze correctly for `0xefdf6abc` wV≈$3.6k and for
`0xfd9b7636` wV≈$11.8k — both live-confirmed Bronze.)

### What each tier is worth, in c/share
Saving vs our current Bronze (`eff_rate = 0.07·(1−rebate)`):

| tier | @p=0.50 | @p=0.90 | @p=0.97 (our lane) | reachable? |
|---|---|---|---|---|
|Silver|0.087|0.031|0.0102|4.5× our fee spend|
|Gold|0.262|0.094|0.0306|45×|
|Platinum|0.507|0.183|0.0591|227×|
|Obsidian|0.823|0.296|0.0957|2,271×|

On **today's** flow (1,908 sh/day, $4.47/day of fee): Bronze $0.134/day,
Silver $0.357/day, Gold $0.804/day. **Even Gold is $293/yr.**

### The kill
- Against a 1.0–2.2 c half-spread and 1–3 c mispricing, even **Obsidian**
  (0.875 c/sh at mid) leaves mid-band cost 1.9–3.1 vs mispricing 1–3. **No cell
  flips, at any tier, even the unreachable ones.**
- **Farming the tier is catastrophically −EV**: reaching Gold means burning
  $6,087 of fees in 30 days (net $4,870 after the 20% maker rebate you'd get back
  only if you were the maker, which you are not) to earn 18% of *future* fees =
  $0.80/day at our size. Payback ~20 years. Explicitly ToS-prohibited if done by
  self-matching ("wash trading, self-matching, or other inauthentic trading" →
  rebate and tier clawback at PM's sole discretion).
- **The Bronze rebate is barely paid in practice.** Our `taker_rebate` atom is
  **$10.00 lifetime, credited once on 2026-08-25** — that is the Bronze level-up
  bonus, not accrued rebate. Zero ongoing rebate in 21 days against ~$130 of fees
  (3% = $3.90 owed). Cross-check: `0xefdf6abc` (Bronze) received **$0.00 across
  07-27→09-15 on $367 of fees**; `0xfd9b7636` (Bronze) received exactly **one**
  credit, $1.277 on 08-28 (3.91% of that day's fee — which does confirm the
  rebate base is the **fee**, not wV). Treat the taker rebate as **0 c/share**
  until proven otherwise.

### Direction of travel is against us
Changelog 2026-02-12 described 5m crypto fees as "peaking at **1.56%** at 50%
probability" ⇒ rate 0.0312. Today `feeType: crypto_fees_v2`, rate **0.07** ⇒
3.5% at 50%. **The crypto taker fee has more than doubled.** Sports went
0.03→0.05 on 07-10 with the maker rebate cut 25%→15%. Do not model a fee cut.

## 2. `holdingRewardsEnabled` — answered, and it is not ours
- **413/413 real 5m crypto bars (7 coins, recent-closed + 24h-pre-open):
  `holdingRewardsEnabled: false`.** Never true on any crypto up/down market.
- Where it IS true (108 of 2,100 open markets scanned): exclusively **long-dated
  politics / geopolitics** — `will-gavin-newsom-win-the-2028-…`,
  `will-china-invade-taiwan-before-2027`, 2026 balance-of-power, etc. Horizons of
  1–3 years.
- It is **absent from every documentation page** (llms.txt, market-details,
  programs/*). The only adjacent documented thing is the **Perps** "OI rewards
  pay 6% APR on the account's full daily average gross OI", and the PnL atom
  `yield_income` exists alongside `reward_income`/`referral_income`. Best read:
  **yield paid on collateral locked in long-horizon positions.**
- **Economic value on 5m crypto: $0.000 c/share.** A 5-minute hold could not earn
  a meaningful carry even if the flag were set (6% APR × 5/525,600 yr ≈ 6e-7 of
  notional).

## 3. Maker-side subsidy — the 20% rebate is the whole of it
- Live on all 413 bars: `feeSchedule {rate 0.07, exponent 1, takerOnly true,
  rebateRate 0.2}`, `makerRebatesFeeShareBps 10000` (= 100% of the allocated
  share; it is a cap, never >100%).
- The docs' pool wording `rebate = (your_fee_eq / total_fee_eq) × rebate_pool`
  with "totals calculated **per market**" is **algebraically 20% of your own
  fee-equivalent, undiluted**: on a matched trade the maker and taker sides share
  the same C and p, so Σ maker fee_eq ≡ Σ taker fee_eq in that market, and the
  pool is 20% of that same total. Archive receipt (20.0% exact) stands.
- Value: `0.2 × 0.07 × p(1−p)` = **0.35 c/sh at p=0.50, 0.041 c/sh at p=0.97**.
- **Crypto already has the best maker rebate per share of any category.** It has
  the lowest *percentage* (20% vs 25% elsewhere, 15% sports) but the highest
  rate: 0.2×0.07 = 0.014 beats politics 0.25×0.04 = 0.010. There is no
  cross-category improvement and no maker volume tier ("Only taker trades earn
  Weighted Volume … Maker trades do not count").
- **Liquidity rewards: $0, twice over.** `GET /rewards/markets/current` returns
  **17,462 markets / $166,541 per day** of native pools, and the previously
  uncatalogued **`?sponsored=true`** returns **40 markets / $7,555 per day** of
  third-party-sponsored pools. **Overlap with 364 live 5m crypto condition ids:
  0 and 0.** `GET /rebates/current?maker_address=…` returns `null` for our days.
- ⭐ New pre-registered kill for the mid-band re-open condition: the CLOB market
  object exposes an undocumented **`r.moas: 30`** (minimum order age, seconds)
  alongside `mi: 50` / `ma: 4.5`. Liquidity-reward scoring on a **300-second bar
  would require a 30-second rest** — 10% of the bar per sample, versus the 3.5 s
  used on March Madness markets. Even if a pool returned, in-band farming is
  far harder than the $1,600–1,800/coin/day trigger assumed.

## 4. Order types / endpoints / pre-open — what is actually unused
**Order types (clob-openapi.yaml, live spec):** `orderType ∈ {GTC, FOK, GTD, FAK}`
only; `postOnly` (GTC/GTD only); no iceberg, no hidden, no stop, no
self-trade-prevention flag.
- ⭐ **`deferExec` (boolean, default false)** on `POST /order` and `POST /orders`.
  Described only as "Whether to defer execution" — **no documentation anywhere**
  and we do not set it. The only genuinely unexplored order-submission flag.
  *API permits ≠ economically live*: its effect is unknown and it would need a
  live order to characterise. Flagged, not recommended.
- **`itode`** (CLOB market object) = "taker order delay enabled; marketable
  orders held for the taker-delay window". **Tested: `true` on every 5m crypto
  market including the 24h-pre-open ones (20/20).** An earlier single sample
  showing it absent did not replicate — there is **no delay-free pre-open seam**.
- Batch `POST /orders` = 1–15 orders; `DELETE /orders` = 1,000 ids (reduced from
  3,000 on 2026-06-15 — the archive's "3,000" is **stale**).
- **A second, separate tier ladder exists and is easy to confuse with the fee
  one: per-signer trading rate limits.** 30d volume $53k ⇒ **Bronze**: 80
  orders/s refill, 120 burst, 160/240 cancel. Not binding at our clip rate, but
  batches are all-or-nothing against the bucket.
- Rate limits (IP): CLOB `/book` 1,500/10s, `/books` 500/10s; gamma `/markets`
  300/10s; data-api v2 general 800/10s, `/v2/trades` 300/10s.
- Pre-open: markets are created exactly 24 h ahead, `acceptingOrders: true`,
  tick 0.01, `moas 30`, fee schedule identical, `holdingRewardsEnabled false`.
  **Nothing at creation/pre-open differs from the live bar except the book.**

## 5. Things checked and closed with a number (do not re-derive)
| Lead | Result |
|---|---|
| `fees_refunded` = 57% of lifetime fees | **Historical only.** Daily series: refunds ran 2026-03-28 → **2026-04-20** (47–84% of fees, the pre-rebates-farmer fee-rollout era) and have been **exactly $0.000 on every day since**. Not a live subsidy. |
| Fee charged on limit price? | **No** — fill-price formula reconciles to 1.0% over 4,721 fills. |
| Fee rounding to zero (min 0.00001 pUSD) | Needs C < 7.14e-5/(p(1−p)) shares: 0.0072 sh at p=0.99, 0.072 sh at p=0.999. `orderMinSize` is 5. **Unreachable.** |
| Lower-fee crypto market variant | **None.** 270 open crypto markets, one `feeType` only: `crypto_fees_v2`, rate 0.07. |
| Sponsored liquidity pools on 5m crypto | **0 of 40 sponsored markets.** |
| Builder Program as a fee offset | Builder fees are **additive**, flat bps of notional, and self-routing pays yourself (net zero). Verified-tier "weekly USDC rewards based on volume" + grants exist but require manual approval and routing **other users'** flow. Not a 5m mechanism. |
| Perps as a subsidy | $75,000/day pool, no allowlist, but eligibility needs **≥1% of trailing-7-day maker volume** — unreachable at this size. Perps taker 0.0400% / maker 0.0125% at tier 0; negative maker fee only above **$1B** 30d volume. |
| Self-matching to farm wV | Costs 80% of the fee net of the maker rebate to buy wV worth 3% of future fees. **−EV by ~2 orders of magnitude**, and explicitly clawback-eligible. |

## 6. If someone wants the fee to fall, these are the only two doors
1. **Trade further from 0.50.** Already what the live lane does; it is worth
   **1.55 c/share** versus a mid-band taker and dwarfs every program on this page
   by 15×–170×.
2. **Be the maker** (fee 0, +0.041 c/sh rebate at p=0.97, +0.35 at p=0.50). Worth
   **0.245 c/sh in our lane, 2.10 c/sh at mid** — the largest fee lever that
   exists on this venue. It is closed by adverse selection (−4.6 c/sh terminal at
   mid; tick-jump infeasible on the venue clock), not by the fee schedule.
   Any maker re-open must beat adverse selection, not find a subsidy.
