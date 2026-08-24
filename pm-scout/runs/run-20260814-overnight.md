# Overnight edge hunt 2026-08-13/14 (user: "keep searching for the strat we can use")

Capital at start: bots wallet **$92.05** pUSD free, 0 open positions;
pm-scout wallet $350 + 3 positions. Live: btc-mintsalvage + sweeper + 10
recorders. Four directions tested to a verdict. **No deployable strategy
found — all four closed negative or inconclusive.** Details below; the
methodology lessons are the durable output.

## 1. Structural arbitrage on PM event markets — DEAD
Ladder monotonicity (nested dates/thresholds) and neg-risk set sums, both
view-free and riskless when they exist. 141 direction-validated ladders → **0
violations**; tightest pairs within 0.1-0.2c of the no-arb bound. Neg-risk sums
1.02-1.09 (normal overround). Three false-positive classes documented in
KNOWLEDGE.md — all three initially looked like free money.

## 2. Resolution-text divergence (the Duma archetype) — mostly priced
206 unique rule-sets read by 5 agents. Geopolitical market makers demonstrably
read the rules: every narrowing clause checked was already in the price.
Survivors, all small: Trump×Greenland YES 0.31 (fair ~0.40-0.50, 251sh depth),
Waymo "12-15 cities" YES 0.232 (fair ~0.38, $2k liq), Ukraine-Donbas YES 0.067
(fair ~0.08-0.13, but only ~$100 of book).
**The valuable result was a REFUTED finding** — see KNOWLEDGE.md: an agent's
high-confidence ~$1,900 HLE trade was killed by one query against resolved
markets in the same family. New standing rule: resolution PRECEDENT outranks
reading the source page.
**Blocked follow-up:** `scan.py:149` truncates descriptions to 600 chars
(13,526/14,762 cut), so this hunt read boilerplate. Fix, then re-run — the scan
almost certainly UNDER-found.

## 3. Cross-sectional momentum refresh — NOT DEPLOYABLE (cost, not decay)
Full detail in memory `pattern-bot/xsectional-findings.md`. Full-sample Sharpe
+1.08, survives a 1-day lag and universe perturbation, reversal control correct
sign — but breakeven is ~20bps/side at ~1.0 daily turnover, and recent years at
a realistic 15bps give Sharpe **+0.04** (2024→) and **−0.22** (2023→). The
entire recent edge sits in the 5→15bps cost gap. mom14 and mom30 disagree on
2026 by ~45pp, so the factor is not stably healthy either.

## 4. PM event-market calibration — INCONCLUSIVE (method failed, diagnosed)
Per-market study (1,807 resolved, high-volume) suggested mid-priced YES legs
realise +5 to +12c above price. **Almost certainly selection bias:** the same
study shows +1c even at T−1h, where markets are effectively decided — a real
edge cannot live there, a winner-oversampling artifact can (conditioning on
≥$50k volume favours legs that ended up mattering).
The event-complete control meant to settle it is **invalid**: per-event prices
sum to **1.37-1.74** instead of 1.00, because legs are sampled at
(their own last point − H) rather than a common wall-clock instant, so dead
legs contribute stale prices. A correct study must align every leg of an event
to the SAME timestamp and verify the per-event sum ≈ 1 before reading any
bucket. Not attempted further tonight.

## 5. Kalshi cross-venue — CLOSED, not testable
API 403s from here even with a browser UA, and the jurisdictions are mutually
exclusive (Kalshi US-only; PM blocks US). Operationally impossible for us.

## Operational notes
- **btc-mintsalvage redeem loop is erroring** every cycle on
  `in-flight transaction limit reached for delegated accounts` /
  `gapped-nonce tx`. It fires redeems without waiting for nonce confirmation so
  all but the first fail. **No capital is stuck** — all 6 redeemable positions
  are worth $0.00 (losing 50sh lots) — but it burns gas and log volume. Fix =
  serialise redeems / await receipt.
- **Hormuz-normal-by-Aug-31 collapsed to 0.02** (was 0.135 on Aug 7). The
  pm-scout 250sh YES is now ~$5, a ~−$33 realised-in-effect loss. Iran-Oman
  agreed a corridor but the US blockade did not lift and traffic kept falling.
- Duma UR **NO** (held 80sh @0.31) now 0.33/0.34 with a deep book (38k sh
  within 2c). Still the largest single edge on the sheet, but it is an
  interpretation bet on UMA reading the delta clause literally, not a strategy.

## Bottom line
Idea generation is not the binding constraint — **execution cost and capital
are**. Every mechanical edge tested is either arbitraged away (PM structural,
PM rules-text) or smaller than our trading costs (momentum). The cheapest
high-value follow-up is fixing the 600-char truncation and re-running the
divergence hunt, which is the only lane where we have a durable advantage
(reading 14k rule-sets) and which ran crippled tonight.

---

# SECOND WAVE (after fixing the truncation bug)

`scan.py` now stores full descriptions (was 600 chars). Re-scan
`scan-20260813-2109.json` (14,634 markets, descriptions up to 5,760 chars).
The bug had hidden **1,059 markets / 383 unique rule-sets** from the first
hunt — and worse, it biased the FILTER itself, since the qualifier regex was
matched against truncated text, so markets whose narrowing clauses live in
paragraphs 3-6 were never even candidates.

Re-read: 240 newly-visible groups + 165 previously-visible groups re-read on
full text (the first wave had only seen their boilerplate).

## ⭐ Best finding: Maduro "No Prison Time" — buy YES ~0.38-0.42
Full workup and verification in KNOWLEDGE.md. Short version: the leg is the
catch-all for the calendar running out ("If no sentencing takes place by
December 31, 2027 ... this market will **also** resolve to 'No Prison Time'"),
trial does not start until **June 1, 2027** (verified: CNN/ABC/MercoPress),
and the Hunter Biden precedent shows the default clause is honoured. Market
implies ~60% that a prison sentence is imposed by the deadline; realistic
sentencing lands Nov 2027 - Mar 2028. Est P(YES) 0.70-0.85 vs 0.38 ask.
**~2,154 sh executable to 0.43 (~$896, avg 0.416).** 16.5-month capital lock
is the real cost. I verified clause, precedent, sibling coherence (asks sum
1.009), book depth and the trial date myself.

## Smaller candidates (all real, all size-limited)
- **AI bubble NO @0.865** — needs 3 of 6 catastrophic triggers (NVDA −50% etc);
  both prior siblings resolved NO. ~$645 executable, +5-8c. Caveat: $2.34M
  lifetime volume, so 14.6c may be a fat-tail premium, not a misread.
- **France United Left primary, NO on "Canceled" @0.084** — "Canceled" needs a
  formal organiser announcement or 3 of 4 NAMED parties withdrawing; the
  parties that actually killed it (PS, PCF) are not among the four, and a
  postponement explicitly does not qualify. Everything else falls to "Other".
  ~3,832 sh / $338 total. Est fair 0.12-0.20.
- **NZ coalition "Cabinet post" clause** — Greens have NEVER held a NZ Cabinet
  post (always ministers *outside* Cabinet); Dutch sibling with the same clause
  resolved correctly. Only ~$30 on the 11x leg, ~$700 on the +30% leg.
- **Trump-insult dailies, NO @<=0.10** — 123 settled days: 88.6% lifetime,
  ~78-80% trailing, vs 0.87-0.94 priced. Only ~$174 executable.

## The verification rule paid for itself four times
Every one of these was a confident, large, WRONG call, killed by checking what
actually settled rather than re-reading a source page:
1. **HLE complex** (~$1,900, "87c edge") — resolved siblings settled ABOVE the
   leaderboard ceiling the agent read.
2. **OpenAI (LOW) valuation markets** — descriptions are a verbatim copy of the
   (HIGH) template, so LOW-$600B looks already-true at an 0.08 ask; but across
   the identical family (Anduril/Stripe/ByteDance/Kraken/Perplexity/Epic) the
   HIGHEST rung settles YES and lower rungs stay open and cheap => UMA resolves
   on intent.
3. **NATO x Russia "clash"** — text counts non-munition UAV shootdowns, but the
   June-30 sibling settled NO despite the June 8 Latvia shootdown.
4. **Abraham Accords / Kazakhstan** — killed by four resolved NO siblings.

## Two more durable gotchas
- **`liq` is not executable depth** — overstated by 20-50x in places ($10,285
  `liq` vs $53 real at the touch). Always size off `/book`.
- **`endDate` frequently contradicts the rules text** and is sometimes already
  in the past (Lyman shows 2025-12-31 with a `createdAt` of 2026-02-19;
  US-strike-on-Colombia shows 2026-01-31 against a Dec-31-2026 rule). Anything
  that filters, expires or sizes capital-lock off `end` will mis-handle these.

## Checked, not an edge
Clacton by-election (Farage): the "if the candidate does not compete, resolve
to the lowest bracket" default looked explosive with "under 40%" at 0.003 —
but Farage resigned **specifically to re-contest** the seat, so the default
never fires. Election was held 2026-08-13 with Labour/Con/LD/Green standing
aside; polling had Farage 73% vs the 70-80% bucket at 0.52. A forecasting
question with no informational edge for us, resolving within hours.
