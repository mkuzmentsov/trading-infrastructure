# poolfarm — 5m liquidity-rewards pair farming. VERDICT: DEAD (every variant)

Code: `src/poolfarm.py` (shared with 15m/1h via BAR_SECONDS). Bot yaml
`chart/bots/btc_poolfarm.yaml`. Ran LIVE 2026-08-12 (two sessions).

## Thesis
Rest 50sh BUY on BOTH sides at floor(mid−EDGE_C) inside the reward band
(rewardsMinSize=50, maxSpread 4.5¢; $10k/day btc-5m pool + 20% maker-rebate
pool). Income = rewards + rebates; trading only has to not-bleed.
Observed income day 1: +$4.67 liquidity reward + $21.69 maker rebate.

## Everything tried, in order, with dates and results

| # | date | variant / combination | result |
|---|---|---|---|
| 1 | 08-12 00:20 | v1 CHASE (re-center each tick, exit sells at +2 ticks, partner-cancel on fill) | −$111 night. Decomposed: chasing 54% (17 high-churn bars, pair 1.063), exit round-trips + partner-cancel 96% of remaining (one-sided bets up@0.87 etc.) |
| 2 | 08-12 | v2 NO-CHASE + reband-only + hold-to-redemption (removed exits + partner-cancel) | first live bar −$14.50: whipsaw pair 1.29 (UP@0.72 early + DOWN@0.57 late, each below its own mid at the time) |
| 3 | 08-12 | vol-pull (cancel both sides on >1.5¢ tick move) | env never plumbed → default fired EVERY tick → blocked ALL quoting. REMOVED from code entirely |
| 4 | 08-12 | PAIR-COST CEILING (2nd leg capped at floor(0.985−leg1); standing violator cancelled instantly) | pairs fixed: live 0.97/0.98 pairs +$1.00/+$0.99; backtest median 1.120→0.980, 100%<1.00 |
| 5 | 08-12 | ceiling + hold: the SOLO leg problem surfaces | one-sided down@0.56 lost −$28 → day halt −$25.50. Solo legs = the entire loss |
| 6 | 08-12/13 | fast UNWIND of solo legs (2-15s grace, sim) | −$15/day @1¢ haircut, −$85/day @2¢ — sells into the adverse gap. DEAD |
| 7 | 08-13 | volatility gate (quote only calm mids), sweep 1.5-5¢/12s | solo fills only drop 42%→13%, worst bar still −$31, reward presence collapses when calm-only. DEAD |
| 8 | 08-13 | deep edge 4.0-4.5¢ (reward band edge) ± vol gate | solo still 11%, worst −$29. The "deeper = more profit" backtest signature was a fill-model artifact (win% pinned at 68% while profit rose = impossible under real adverse selection). DEAD |
| 9 | 08-13 | reactive MAKER pair-completion (aggressive 2nd-leg maker after leg-1 fill, pay up to 1.05 pair) | solo holds unchanged 42%→40%, worst −$43 at every cap. ROOT CAUSE: in one-directional flow there is NO counterparty on the needed side at ANY price. DEAD |
| 10 | 08-13 | predictive pull (cancel on adverse mid move; reaction 0.1-0.5s incl co-location bound) | worst bar identical at every latency — damaging fills are ATOMIC single-tick sweeps; you cannot cancel an order being matched. Latency/cores/location irrelevant. DEAD |
| 11 | 08-13 | fair-zone mid band [0.40-0.60] / [0.45-0.55] | reveals the 67% solo "win rate" was extreme-mid base-rate artifact; fair-zone solo win = 49-52% (coin flip). No band is +EV |
| 12 | 08-13 | BATCH pairs (10/25/50sh increments, imbalance ≤1 batch) on 5m data | matched shares/bar = 0 at every batch size (no oscillation time in 300s), net −$3..−$7/day. DEAD |
| 13 | 08-13 | taker-completion of leg 2 — priced exactly | immediate: pair 1.006-1.008 (spread + fee 0.07·p(1−p)) = −$0.33/pair guaranteed; delayed = unwind economics minus a tick minus fee (strictly worse). Only usable as insurance if P(maker completion) < ~22% |

## Execution bugs found live (fixed, keep in any revival)
- **Sticky halt latch** (`_halt_day` per UTC day): day_pnl recovering used to
  un-halt 70s after a halt.
- **Per-side inventory cap checked UNCONDITIONALLY on self.inv** (the
  bar_fills counter guard sat after the reband `continue` and was bypassed →
  150/50 over-accumulation, −$53 + collateral drain + order storm, 08-13).
- CLOB "not enough balance/allowance" storm = collateral genuinely consumed
  (the balance VIEW lag is tens of $, not $100) — check positions, don't
  restart mid-bar (in-memory inventory resets → re-buys).

## zec variant ("the book is empty, let's BE the market") — DEAD, 2026-08-16

Asked: btc-5m failed because informed flow ran over our solo legs; zec-5m has
no flow at all, so does MM'ing an empty book work? Census over the zec-mrec
raw logs, 2026-08-14 21:00 → 08-16 08:00 UTC (35 files, 5,851,098 SNAP rows,
1,168,611 cur-role, 411 bars):

| measure | zec-5m |
|---|---|
| series taker volume | **$185.37 / 34h ≈ $131/day** |
| bars with ANY trade | 40 / 411 (90% of bars: zero) |
| trade prints | 49, sizes 5–15sh |
| price of those prints | **49/49 at 0.99–0.999** |
| timing | tl ≈ 30–45s (late-bar) |
| cur-snaps whose book is the 0.01/0.99 5sh stub | 902,579 / 1,040,488 = **87%** |
| cur-snaps with spread ≤10¢ | 3.5% |

Both income legs price out to zero:
- **Rebate** = rebateRate 0.2 × taker fee 0.07·p(1−p). At p=0.99 that is
  $0.0001386/sh. Even as maker on *every* print (~180sh/day) = **$0.025/day**
  — and being that maker means selling the winner at 0.99, i.e. paying
  ~$1.80/day in trading loss to earn 2.5¢. The only flow on zec IS the
  pick-off.
- **Rewards**: config is present and identical to btc (`rewardsMinSize` 50,
  `rewardsMaxSpread` 4.5, `makerRebatesFeeShareBps` 10000, `feeSchedule`
  {rate 0.07, rebateRate 0.2}), but CLOB `rewards.rates` is null and — the
  decisive tell — **nobody quotes it**. btc-5m carries 200–330sh at the touch
  from pro farmers; a funded pool on an empty book would be the most obvious
  free money on the venue and would not sit unclaimed for 34h. Pool = $0.

Reference point: on btc-5m, where the income legs are REAL ($4.67 reward +
$21.69 rebate day 1), poolfarm still lost $111 in a night. zec keeps the
adverse selection (100% of flow is informed) and deletes the income.

**Standing lesson: "no liquidity" is not an opening.** MM revenue is
proportional to *uninformed* flow, and you cannot manufacture it. An empty
book on a 5-minute binary means no counterparty except the one person who
already knows the answer.

Only open variable = the pool question, settleable for ~$50: rest 50sh
two-sided inside the band on zec for one day (`src/poolfarm.py` already does
this — `coin: zec` + a bot yaml, no new code) and read the earnings ledger.
Expected fills ≈ 0 (nothing traded away from 0.99 in 34h), so expected result
is $0 both ways. Not recommended; logged so nobody re-derives it.

## Why it is dead (one sentence)
5m bars have no time for the second leg to fill (informed one-directional
flow, no oscillation), so the strategy IS its solo legs, and solo legs at any
band/depth/timing are a coin flip at best and adversely run-over at worst.
