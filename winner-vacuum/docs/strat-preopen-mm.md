# Pre-open signal-informed MAKER ("be the puller") — census done 2026-08-31. Real pool, but it belongs to the incumbent. NOT deployable on current evidence.

Context: the openlag probe (strat-openlag.md) proved live that pre-open
in-band asks are quoted by someone who (a) pulls on contact (4/5 of our FAKs
killed), (b) prices displacement correctly (the 08-31 six-coin reversal bar:
all six 0.75-0.85 asks won for the maker; our skip-counterfactual −$33.23).
Question (user, 08-31, analysis-only mandate): can WE be that maker? The old
"pre-open maker DEAD" verdict ([strat-preopen](strat-preopen.md)) was
measured on FLAT 0.48-0.55 quotes without the strike signal — a different
strategy, so the question was open.

## The census (the honest first step — incumbents' achieved economics)

Every deduped pre-open print in the last 60s before open, cl-era archive
08-22→29, 7 coins: **192,528 prints, $2.70M maker notional**. Maker PnL per
print = px − won (BUY prints) / won − px (SELL prints), no fee (makers pay
none). Tool: `tools/openlag/extract_premm.py` + `premm_census.py` +
`premm_day.py` (mirrored from session scratchpad).

**Aggregate: makers LOSE −$10,088 / 8d = −$1,261/day (−0.37%).** The wall
stands in aggregate. But the interior is sharply structured:

| cut | maker PnL | note |
|---|---|---|
| 10-60s before open | **−1.14%** | stale quotes eaten by informed takers — this is where the old flat-quote corpse lies |
| 3-10s | **+0.83%** | book repriced by now |
| 0-3s | **+3.09%** | late takers overpay vs the repriced book |
| \|z\|≥1.2 bars | **+6.39%** | the reversal-bar lesson at scale: high-displacement asks are the informed side |
| \|z\| 0.5-1.2 | **−2.76%** | the residual openlag seam, seen from the maker's side |
| px 0.45-0.55 | −1.33% | the flat-quoter graveyard |
| px 0.55-0.90 | +0.4…+7.4% | displacement-priced quotes win |

The last-10s maker pool = **+$11.4k/8d ≈ +$1.4k/day gross** — bigger than
the post-close sell-into-bid pool ($315/day).

## Why it is NOT a strategy (robustness cuts)

1. **btc is the entire pool**: btc +$13,921 (+2.09% on $667k); every other
   coin negative except sol (+$972); bnb/doge/hype/xrp −4…−15%.
2. **Day-unstable and back-loaded**: 0-10s slice 5/8 days positive, all the
   profit in 08-26→29; 0-3s swings −10.7% → +21.4%/day. The aggregate's
   sign flipped mid-week — consistent with ONE incumbent scaling up on btc
   and collecting; the census tracks THEIR skill, not a field condition.
3. **Selection**: by the final seconds only the smart maker's repriced
   quotes remain standing (stale ones were eaten at 10-60s or pulled). The
   census average is the achieved outcome of surviving quotes; an entrant's
   marginal resting order joins the dumb tail — the exact
   [[maker-resting-order-wall]] mechanism, unrefuted here.
4. Going further would need a join-time queue sim (bug ledger #11) plus a
   live micro-probe; the composition evidence (1 coin, 4 days) already
   fails the §47 fingerprint discipline, so neither is justified now.

**Verdict: ⛔ parked.** The one legitimately-new mechanism found in the
08-31 exhaustive survey, and it is owned by incumbent skill. Re-open only
if a future census (same tools, ~10 min) shows the late-window pool
positive across ≥4 coins and ≥75% of days.

## The rest of the 08-31 "anything left?" survey (all dead or blocked)

| idea | verdict |
|---|---|
| Funding-timestamp bars (00/08/16 UTC drift) | ⛔ noise — "after funding" cell flips sign between eras (61% UP cl-era vs 39% old archive); AT-funding UP-lean ~1.5σ pooled at cluster level; sub-spread anyway |
| Cross-venue 5m arb | ⛔ structurally impossible — no second leg: Kalshi is 15m on its own index (99¢/0¢ payout); nobody else lists 5m crypto binaries |
| Delta-hedged vol harvesting (binary + PM perps) | ⛔ analytically dead — full-range calibration says win% ≈ price − spread in every (px, tl) cell ⇒ no vol mispricing beyond the spread; perp fees + hedge error are pure add-on cost |
| Consecutive-bar coupling (bar N's settle TWAP ≡ bar N+1's strike) | ⛔ outcomes are martingale increments; bar-to-bar carryover measured dead (07-29 structure hunt) |
| Vol-event pre-positioning (buy both sides pre-CPI) | ⛔ impossible by arithmetic — the binary pair settles to exactly $1; there is no long-vol structure in a complementary pair |
| September rewards program | 🔍 none announced as of 08-31 (changelog ends at the 08-17 taker-delay entry); August $1M program expires today — re-check docs/programs after 09-01; a new program could revive reward-farming math |
| Combos (RFQ parlays) on 5m legs | 🔍 still gated / eligibility undocumented; correlation-pricing game IF it opens — watch item |

**Survey conclusion**: at analysis level the 5m space is exhausted — every
remaining direction is measured-dead, structurally impossible, or
incumbent-owned. The open items are watch-items (rewards, combos, the two
standing re-check pipelines), not build candidates.
