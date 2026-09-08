# Polymarket beyond 5m crypto up/down — venue-wide strategy survey (2026-09-08)

**User mandate:** *"investigate more about polymarket and implement new tools to trading-mcp (combos/rewards and
other stuff) … first, investigate what strategies we can execute there. I would like us to bet cheap."*

Scope: everything on Polymarket that is NOT the 5m crypto up/down fleet. That programme is separately documented
(`README.md` §, `strat-*`); its maker lanes are closed (see [[maker-resting-order-wall]],
`strat-midband-mm-rewards-20260907.md`). This doc asks what else the venue offers.

All numbers below are from live APIs on 2026-09-08 ~19:00-21:00 UTC, over a 2,100-market open-market census
(gamma caps pagination there). Books were read from `POST /clob/books`, never from gamma's cached
`bestBid`/`bestAsk` — bug #39 / §72 (ghost quotes) applies to every availability statistic.

---

## 1. What is new on the venue since the 5m programme was written

| Thing | Status | Where |
|---|---|---|
| **Combos / RFQ** — multi-leg conjunction positions, quoted by competing MMs in a 400 ms auction | catalog LIVE, execution **NOT open**: every market returns `pending: true`, `rfqEnabled: false` on all 2,100 | `combos-rfq-api.polymarket.com/v1/rfq/combo-markets` |
| **Perps** — Polymarket now runs a perpetual futures exchange with its own liquidity-rewards programme | live, **unexamined** | `/perps/*` docs |
| `holdingRewardsEnabled` | **true on 228 of 2,100** open markets; undocumented — absent from llms.txt and the changelog | gamma market field |
| Taker Rebate tiers (Bronze→Obsidian, 3%→50%) | live since 2026-05-28; we are tier 0 | `/programs/taker-rebates` |
| Crypto taker delay 250 ms → 50 ms | 2026-08-17 | changelog |
| Session keys (scoped, time-limited signer) | live | `/trading/session-keys` |

**Category fee/rebate table** (this is the lever that decides everything below):

| Category | Taker rate | Maker rebate |
|---|---|---|
| Crypto | 0.07 | 20% |
| Sports | 0.05 | 15% |
| Politics / Finance / Mentions / Tech | 0.04 | 25% |
| Economics / Culture / Weather / Other | 0.05 | 25% |
| **Geopolitics & world events** | **0** | fee-free |

Taker fee per share = `rate × p × (1−p)`. **150 of 2,100 open markets are fee-free.**

---

## 2. ⛔ Neg-risk basket arbitrage — CLOSED

1,150 of 2,100 open markets are `negRisk`, in 224 multi-outcome groups. Both directions tested against real books.

**`sum(ask) < 1` is not an arb.** Lowest observed: `nobel-peace-prize-winner-2026` at **0.4100** across 20 legs —
verified real (0 legs missing an ask, gamma and CLOB agree to 4dp). It is not free money: these are *augmented*
neg-risk events carrying unnamed placeholder slots and an "Other" outcome, so the listed legs are not a complete
partition. A sum of 0.41 is the market pricing a 59% chance the winner is unlisted. Same story for
`republican-presidential-nominee-2028` (0.9220 / 42 legs) and `democratic-presidential-nominee-2028` (0.9330 / 51).

**`sum(bid) > 1` is the genuine direction** — mint a YES+NO pair for $1, sell both into the bids; an unlisted
winner only helps the seller. It exists gross (`ballon-dor-winner-2026` 1.0110, `nc-11-house-election-winner`
1.0100, `tx-15-house-election-winner` 1.0100) and **dies net of the taker fee on all 224 events**. Best net edge
on the venue right now: **−0.0014** (`massachusetts-governor-winner-2026`). Hitting a bid makes you the taker, and
`rate × p × (1−p)` at mid prices is ≈1c/share — exactly the gross edge.

This reproduces [[leaderboard-closed]] ("fee 1.7× the gross edge") on a completely different market family. The
tool `polymarket_scan_negrisk` now reports `sell_field_net_edge` so this cannot be mis-read again.

*Re-open condition:* a fee-free (Geopolitics) neg-risk group with `sum_bid > 1`. None today; the scanner surfaces it.

---

## 3. ✅ Liquidity-reward farming on low-competition markets — the open lane

Unlike 5m crypto (where `clobRewards = 0`, [[rewfarm]]), the long-dated book **does** carry live pools.

* **648-817 open markets carry a live pool** (count varies with the census slice); **$4,400-6,200/day total**.
* Configs are current, not stale: `endDate: 2500-12-31`, e.g. `openai-announces-it-has-achieved-agi-before-2027`
  $300/day since 2026-05-25, `will-the-us-invade-iran-before-2027` $400/day since 2026-04-29.
* Scoring (`/programs/liquidity-rewards`): quadratic in distance from midpoint, `Q_min = min(Q_one, Q_two)`,
  sampled every minute over 10,080 samples/epoch, then normalised across makers. **A sole qualifying maker takes
  the whole pool.** Single-sided scores at 1/3 only while mid ∈ [0.10, 0.90]; outside that band two-sided is
  mandatory. Orders must rest ≥3.5 s to be eligible. Payout floor $1/day.

**The finding: many pools have literally nobody quoting inside the reward band.** Measured as resting size
≥ `rewardsMinSize` within `rewardsMaxSpread` of the midpoint — the only orders that score:

| pool $/day | competition | capital | book | market |
|---|---|---|---|---|
| **62** | **0 shares** | $20 | 0.32 / 0.78 | `will-the-democratic-party-win-the-ny-17-house-seat` |
| 5 | 0 | $20-50 | wide | 9 × `will-{uni,pumpfun,chainlink,ethena}-reach-…`, `workhorse-bankruptcy`, `hyperbeat-fdv-…` |
| 50 | 529 sh | $50 | 0.01 | `will-the-10-year-treasury-yield-hit-5pt0-before-2027` |

NY-17's pool **opened today** (`startDate: 2026-09-08`) — that is why the band is empty. This is a recurring,
harvestable event: new pools appear with no incumbent.

**Honest accounting.** The headline "310%/day" is `pool ÷ minimum capital` and assumes the band stays empty. It
will not. The real risks, in order:
1. **Adverse selection.** NY-17's book is 0.32/0.78 — a 46c spread. The "midpoint" 0.55 carries almost no
   information, and quoting inside it is an invitation. Sizing at the $20 minimum caps a pickoff at a few dollars
   against a $62/day pool, which is why the *minimum* qualifying quote, not a large one, is the right shape here.
   This is the opposite of [[maker-resting-order-wall]] (measured on 5m crypto, where flow is fast and informed):
   NY-17 did $680 of volume in 24 h. Near-zero flow is the whole point.
2. **The $1/day payout floor** kills every row modelled under ~$1 — most of the long tail is unbankable.
3. **Competition arrives.** Yield decays as `minsz/(minsz+comp)`.

Not deployed. `polymarket_scan_reward_pools` measures it continuously; an arm should be one market, minimum size,
logged against `polymarket_get_reward_percentages` (which shows the live % actually being earned — a 0% there
means the quote is not scoring at all).

---

## 4. 🔍 Open leads, not yet tested

* **`holdingRewardsEnabled` (228 markets)** — undocumented. Every one is long-dated, cheap (0.0015-0.18),
  0.001-tick, mostly negRisk 2028-nomination and geopolitics markets. If it pays yield for *holding* rather than
  quoting, it changes the carry on exactly the cheap asymmetric bets the user asked for. **Next: read the docs
  gap via a live position, or find the payout in `/activity`.**
* **Fee-free Geopolitics (150 markets)** — the only category where a thin edge survives, and the stated re-open
  condition for [[leaderboard-closed]]. Deepest: `will-china-invade-taiwan-before-2027` ($116k v24h, $424k liq,
  0.001 tick), `putin-out-before-2027`, `will-the-iranian-regime-fall-by-the-end-of-2026`.
* **Perps liquidity rewards** — entirely unexamined; a second rewards budget on a venue we already have keys for.
* **Combos** — when `rfq_live` flips true, an RFQ *quoter* is a fee-free maker role with a 400 ms decision window
  and last-look. Watch `polymarket_get_combo_markets().rfq_live`.

---

## 5. Tools shipped this session (`trading-mcp`, 13 → 22 Polymarket tools)

| Tool | Purpose |
|---|---|
| `polymarket_scan_reward_pools` | ⭐ pools ranked by capturable $/day vs **real-book** competition inside the band |
| `polymarket_scan_negrisk` | basket mispricing, both directions, **net of taker fee** |
| `polymarket_scan_cheap_longshots` | cheap asymmetric outcomes + `fee_free` / `holding_rewards` flags |
| `polymarket_get_books` | batch books — a multi-leg thesis must read every leg at one instant |
| `polymarket_get_combo_markets` | combo/RFQ catalog + whether execution is open |
| `polymarket_get_clob_market_info` | authoritative tick / fees / rewards / RFQ (gamma's copy lags) |
| `polymarket_get_price_history` | series + realised vol — will a resting quote be run over before it accrues |
| `polymarket_get_reward_percentages` | live % of each pool the wallet is actually earning |
| `polymarket_check_order_scoring` | is this resting order scoring at all |

---

## 6. Verdicts

| Strategy | Verdict |
|---|---|
| Neg-risk basket arb (both directions) | ⛔ closed — net-negative on all 224 events, best −0.0014 |
| `sum(ask) < 1` as an arb signal | ⛔ artefact of incomplete outcome sets — do not trade |
| Combos / RFQ quoting | ⏸ not executable yet (all `pending`) — watch `rfq_live` |
| Liquidity-reward farming, low-competition long-dated | ✅ **open**, verified pools + verified empty bands — arm small |
| Fee-free Geopolitics | 🔍 the one category where a thin edge survives — untested |
| `holdingRewardsEnabled` | 🔍 undocumented, 228 markets, directly relevant to cheap bets |
| Perps + perps rewards | 🔍 unexamined |
