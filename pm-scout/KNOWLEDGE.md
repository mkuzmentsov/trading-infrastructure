# pm-scout knowledge base

Living document. Read FULLY before every run. Append new findings at the bottom
of the relevant section after every run — this file is the module's memory.

## Fee & rebate model (verified 2026-07-22)
- **Crypto up/down (5m/15m/1h/daily) markets**: taker fee = `shares × 0.07 ×
  price × (1−price)` (peaks 1.75c/share at 50c). **Makers pay $0** and earn a
  daily rebate ≈ **20–25% of the counterparty's taker fee**.
- **Most event markets (politics/geo/sports/econ)**: fee-free both sides
  (pre-existing `feesEnabled=false` markets); check per-market fields.
- **Liquidity rewards program**: rewarded markets pay daily for resting
  two-sided quotes within `rewardsMaxSpread` of the mid with ≥ `rewardsMinSize`
  shares; weight peaks near 50c (`p(1−p)` shaped). Scanner surfaces
  rewards-carrying markets — free income on positions we'd hold anyway.

## Mechanics
- Min order 5 shares; tick 0.01; no dollar minimum (~$0.30 at 6c works).
- **Post-only GTC** exists: `engine/clob.py::place_limit_order` — exchange
  REJECTS a crossing order instead of taker-filling it. Use for all maker entries.
- Neg-risk events: multi-outcome, one resolves YES; NO-sweeps across all
  outcomes can exceed $1 payout — check `negRisk` flag.
- Resolution: UMA oracle or stated source. **ALWAYS read the resolution rules
  text before betting** — many "obvious" bets die on technical resolution terms
  (deadlines, sources, exact thresholds).
- Redemptions are NOT automatic — resolved winning positions must be claimed
  (`engine/redemptions.py`). Scan every run.

## Standing strategy verdicts (do not relitigate without new data)
- **Crypto UpDown 5m/15m: efficient-minus-spread** (2026-07-22 proof, 49k bars
  + 19h tick data): taker −EV at every price/time, maker −EV via adverse
  selection, no time-of-day/TA/vol pocket, no cross-asset lag, TP-scalps below
  martingale. NEVER bet these on price alone; only genuine external info could win.
- **Naive two-sided 50c quoting**: single-fill adverse selection dominates the
  +2c lock (needs >96% both-fill; real ≈90% paper-optimistic) — rebates don't
  close the gap. Mirror-maker btc-mm measured it live 2026-07-22.
- Longshot bias exists but is PRICED here (cheap tails win less than price).

## Scanner coverage (2026-07-22)
- `scan.py` does FULL-coverage sweeps: 5 global orderings (newest, 24h-volume,
  all-time-volume, liquidity, closing-soon) + per-category newest+volume passes
  for 11 high-level tags (Politics 2, Crypto 21, Sports 1, Business 107,
  Economy 100328, Geopolitics 100265, World 101970, Culture 596, Elections 144,
  Middle East 154, AI 439). Gamma caps pagination at ~2100 offset (422), so the
  multi-slice approach is what gets past it. Yields ~11.5k markets/run (was
  ~3k). Each record carries `cats` (matched high-level tags) for triage.

## Analysis doctrine
- Newest markets take precedence (early prices are least efficient; first
  liquidity is often lazy 50/50 or anchored wrong).
- Insider/whale flow is REAL signal on PM: enormous one-sided prints without
  public news often front-run announcements (flow.py detects). Follow smart
  entries cautiously; treat dumps against our side as close-warnings.
- Estimate probability FIRST (before looking hard at the price) to avoid
  anchoring; state confidence; only sizeable edge (≥5–10c after fees) is
  actionable given research uncertainty.
- **Resolution timing is part of every bet**: know WHEN each market resolves
  (endDate + resolution lag — sports settle in hours; UMA-disputed events can
  take days; econ markets settle on the announcement). Every bet line must show
  time-to-resolution and capital lock-up. At equal edge prefer the sooner
  resolution (capital recycles): compare bets on **edge per day locked**, not
  raw edge. A 3c edge resolving tomorrow beats 10c resolving in 3 months.
- Sizing: edge-and-confidence weighted, ≤20% of run bankroll per bet, keep
  ~20% reserve. Prefer maker entries (price improvement + rebates/rewards);
  taker only when the thesis is time-critical.
- If a position already exists in a market: never open an independent new bet —
  only HOLD / CLOSE / INCREASE via the portfolio-review section.

## Calibration ledger (append per resolved bet)
| date | market | side | entry | est.prob | outcome | pnl | lesson |
|------|--------|------|-------|----------|---------|-----|--------|
| 07-24 | US-Iran ceasefire by Jul24 | NO | 0.913 | 0.96 | WON | +$5.7 | carry as planned |
| 07-31 | Hormuz normal by Jul31 | NO | 0.99 | 0.999 | WON | +$1.2 | carry as planned |
| 07-31 | Iran leadership change Jul31 | NO | 0.952 | 0.97 | WON | +$2.0 | carry as planned |
| 07-31 | BTC $70k in July | YES | 0.27 | 0.36 | LOST | −$69.9 | own-vol GBM touch model: model/price <1.5× = noise, skip |
| 07-29 | Fed +25bps July | YES | 0.159/0.195 | 0.33 | LOST | −$160 | EV was real (FedWatch 36%) but 38% of bankroll on one binary — the 20% cap exists, enforce it |
| 07-31 | ETH $2k in July | YES | 0.57 | 0.63 | ? | ? | outcome not yet backfilled |

- 2026-08-07: crude-ATH-Sept YES + regime-fall-2027 YES vanished from
  positions without ledger entries — wallet gets touched outside pm-scout
  sessions; always re-pull positions at run start, never trust the ledger as
  the position source of truth.
- 2026-08-07: resolution-text arbitrage found live: Duma "gain the most seats"
  event prices 0.70 on the colloquial reading while the description is
  explicitly delta ("compared to before the election"). Only prior same-name
  template (Chile Senate 311) had different text and UMA resolved literally
  per its text. Rule: when title and description diverge, the description is
  the bet — but cap size (clarification/intent-vote risk) and watch for
  official Polymarket clarifications, exit instantly if one flips the reading.

## Run log pointers
- Run records: `pm-scout/runs/run-<ts>.md`; orders: `pm-scout/runs/ledger.jsonl`.

## Structural arbitrage on event markets — MEASURED DEAD (2026-08-13 night)
Tested the two mechanical, view-free edge families across a 14k-market snapshot
(`scratchpad arb3.py`, `negrisk_arb.py`). Both are efficiently priced:

- **F2 monotone ladders** (nested date/threshold rungs: P(by Aug 15) <= P(by
  Aug 31); P(BTC>=$180k) <= P(BTC>=$170k)). Arb = buy YES(wide) + NO(narrow),
  min payout 1, riskless iff ask(wide) < bid(narrow). Result over 141
  direction-validated ladders: **0 violations**; tightest pairs sit within
  0.1-0.2c of the no-arb bound (BTC/ETH/SOL barrier ladders, Fed upper-bound).
- **F1 neg-risk sums** (exactly one outcome wins): buy-all-NO profits iff
  sum(YES bids) > 1; buy-all-YES iff sum(YES asks) < 1. Correctly grouped and
  live-book priced: sums are **1.02-1.09** (normal overround). No arb.

**Three false-positive classes that each looked like free money — the real
lesson of the exercise (all are generic set-pricing traps):**
1. **Operator swallowed into the parsed number** -> "less than 180m" compared
   against "at least 220m" (disjoint events, not nested).
2. **Unproven subset direction** -> "(LOW)" barrier markets and "will X *not*
   Y by <date>" invert which side is the narrower event; a bare "be 27C" is an
   equality BUCKET (mutually exclusive), never a threshold.
   Fix that generalises: a DOUBLE-LOCK — the parsed operator's implied
   direction must agree with the ladder's empirical price shape (Spearman
   |rho| >= 0.8 over >= 3 rungs). Bucket ladders are hump-shaped, so they fail
   the shape test automatically. Discard whatever you cannot prove.
3. **Set sums computed off a paginated sweep** -> the sweep missed outcomes,
   so "Largest Company end of 2026" summed 4 legs to 0.88 (=12% "riskless")
   when the true 8-leg set sums to 1.022. **Never compute a set-sum from a
   scan; always refetch the complete group from /events (or by
   negRiskMarketID) before believing any number.**
   Note `negRiskMarketID` is the true mutually-exclusive group id — the event
   TITLE is not (the OpenAI event holds both the by-2026 and by-2027 sets, so
   grouping by title sums to ~2.0 and fakes a 90c edge).

Do not reopen structural arb without a new mechanism (e.g. cross-venue vs
Kalshi, or same-underlying event pairs across different PM events).

## Resolution-text divergence hunt — 206 descriptions read (2026-08-13 night)
Thesis: PM prices track the colloquial reading of a market TITLE while the
oracle resolves on the DESCRIPTION; an LLM can read all 14k rule-sets, retail
and mechanical bots cannot. Five readers covered 206 unique descriptions
(deduped from 721 qualifier-matching markets, liq >= $500).

**Verdict: the venue is mostly efficient on this too.** Where a divergence is
real, the price usually already reflects it. Small candidates only:
- Trump x Greenland deal by Dec 31 (`trump-x-greenland-deal-signed-by-december-31`):
  rules count "any agreement... relating to Greenland... regardless of subject
  matter", ratification explicitly NOT required. YES ask 0.31 (bid 0.26, depth
  251sh @<=+2c), literal fair ~0.40-0.50. Sibling proof the market is NOT on
  the naive reading: acquire-Greenland trades 0.037. Medium confidence.
- Waymo "12-15 cities" (`will-waymo-operate-in-12-15-cities-...`): rules count
  only fully-public service areas ("invite-only will not qualify"), and
  region = one city. YES ask 0.232, literal fair ~0.38. Thin ($2k liq).
- Duma UR NO (held): still the biggest single edge — deep book (38k sh within
  2c), NO ask 0.34; literal (delta) reading implies ~0.95.

**⚠️ THE MOST IMPORTANT RESULT WAS A REFUTED FINDING.** One reader returned a
high-confidence "monster": the Humanity's-Last-Exam complex resolves on
agi.safe.ai, whose visible table tops out at **38.3%** and has never listed a
Meta or Moonshot model — so "Kimi >= 45%" at 0.95 looked like a free ~87c,
~$1,900 deployable. **It is WRONG.** Resolved-market precedent on the SAME
source settles it in one query:
  next-Claude-Opus-debut >= 50%  -> YES
  Gemini >= 45%                  -> YES
  OpenAI GPT >= 40%              -> YES
All settled ABOVE that 38.3% "ceiling", so PM does not resolve off the stale
static table (a second reader correctly identified a JS-rendered chart as the
binding artifact). Taking the trade would have been a straight loss.
**RULE, now standing: before betting any "the resolution SOURCE says X"
thesis, query the resolved markets in the same family
(`/public-search` + `closed=true`) and check what actually settled. Resolution
PRECEDENT outranks anybody's reading of the source page — including mine.**
Corollary: independent readers disagreeing is signal, not noise; the cheap
tiebreak is always realised history, never re-reading the page.

**Pipeline bug found by the readers (fix before the next hunt):**
`scan.py:149` truncates `description` to **600 chars** — 13,526 of 14,762
markets are cut exactly there, and PM's operative narrowing clauses almost
always sit in paragraphs 3-6. The whole divergence scan was reading boilerplate
until the readers re-pulled full text per slug (note: gamma 403s `urllib`'s
default UA; send a browser/curl UA). Raise the cap before re-running.

**Metadata hazard:** many markets carry an `endDate` that contradicts their own
rules text (Romania/Israel PM show 2026-12-31 vs rules to 2027-12-31; Ethiopia
2026-06-01 vs 2028; Russia-invades-NATO shows an already-past 2025-12-31).
Never size capital-lock or expiry off `endDate` alone — read the rules date.

## Duma "gain the most seats" — CORRECTED analysis (2026-08-14)
Earlier entries in this file put fair value for UR **NO** at 0.70-0.75. That was
too generous. Full workup:

**For the literal (delta) reading — strong:**
- Text is explicit and unambiguous: "the party that gains the greatest number
  of seats ... **compared to before the election**" + "based **solely** on the
  number of seats gained". No clarification has been appended (checked).
- PM lists a SEPARATE, parallel event **"Russia Parliamentary Election Winner"**
  ("the party that **wins** the greatest number of seats") where UR trades
  **0.982**. Two events, deliberately different verbs, 32c apart — "gain" is
  meant to differ from "win", else the second event is pointless.
- The "gain" wording is a one-off: 1 such event vs **20** "win the most seats"
  events across the venue. It was written deliberately.
- Under delta UR cannot win: it holds 324/450 and polls ~231 (delta ~ −93);
  New People goes ~13 -> ~57 (+44) and would be the winner. NL trades 0.253.

**Against — the precedent, and it is the reason to size small:**
- The ONLY resolved market in this family, **Chile Senate 311**, used
  "gains the greatest number of Senate seats **as a result of the 2025
  election**" / "based solely on the number of seats gained" and resolved to
  **Unidad por Chile** — the pact that WON the most seats (20), NOT the biggest
  increase (Cambio por Chile went 1 -> 7, +6). So the resolver's instinct on
  near-identical wording was **seats-won, not delta**.
- Chile's text lacks "compared to before the election", which is exactly the
  clause doing all the work in Russia — so it is not a clean precedent. But it
  shows which way an ambiguous resolver leans.

**What the market implies (the number that matters).** With UR ~0.03 under
delta and ~0.98 under colloquial, UR-gain at 0.66 implies
  P(delta reading) = (0.98 − 0.66) / (0.98 − 0.03) ≈ **0.34**.
NO at 0.34 is therefore priced almost exactly at the market's implied
probability of the literal reading — **it is NOT free money**, it is a
straight bet that P(delta) > ~34%. My estimate is 0.50-0.65 (the separate
"win" event is the strongest single argument), giving ~+0.16 to +0.31/share of
edge — real, but an interpretation bet with binary risk, not a strategy.
Book is deep (38k sh within 2c of 0.34), so size is a choice, not a constraint.
**Watch for:** any PM clarification (exit instantly if it adopts "seats won"),
and the UMA proposal when it lands (Sept 18-20 election, rules deadline
2027-09-30 — NOT the displayed 2026-09-30 endDate).

## ⭐ Best candidate found in the full-text rescan: Maduro "No Prison Time"
`will-nicols-maduro-be-sentenced-to-no-prison-time-974` (event `maduro-prison-time-527`).
**I verified every load-bearing claim myself** — clause, precedent, sibling
consistency, book depth, and the trial date via independent news.

- **The clause (own market text):** "If no sentencing takes place by
  December 31, 2027, 11:59 PM ET, this market will **also** resolve to
  'No Prison Time.'" Plus acquittal / mistrial / non-custodial sentence.
  So this leg is the CATCH-ALL for the calendar running out.
- **Precedent PASSES** (the mandatory check): `hunter-biden-prison-time-in-gun-sentence`
  used the identical default template; Hunter was pardoned, **no sentencing ever
  occurred, and "No prison time" resolved YES `["1","0"]`**. The clause is
  honored, not waived.
- **Timeline (verified via CNN/ABC/MercoPress):** Judge Hellerstein set trial
  for **June 1, 2027** — only ~7 months before the market deadline — on a joint
  request, in a 6-defendant classified-evidence (CIPA) case, with the
  sovereign-immunity dismissal motion not even heard until **Nov 17, 2026**.
  A months-long trial plus the mandatory PSR interval puts realistic sentencing
  in **Nov 2027 – Mar 2028**, straddling the deadline in the BEST case.
  Comparable verdict->sentencing gaps: Diddy 3mo, El Chapo 5, SBF 5, Maxwell 6.
- **What the market says:** brackets are internally consistent (asks sum 1.009)
  and imply **P(a prison sentence is imposed by Dec 31 2027) ~ 0.60**
  (<20 0.068 + 20-40 0.077 + 40-60 0.084 + 60+ 0.40). That is hard to reconcile
  with a trial that starts June 2027 — and with `maduro-guilty-of-all-counts`
  (same deadline) at only **0.26/0.28**.
- **Estimate P(YES) 0.70-0.85** vs ask 0.38. **Executable: 2,154 sh to 0.43
  (~$896, avg 0.416)**; bid side thick (1,661@0.35, 4,608@0.30) so resting bids
  could add size. Resolves 2027-12-31 => ~16.5-month capital lock (the main
  cost of the trade).
- **Kills:** PM clarifying/extending the deadline (Hunter precedent argues
  against); an expedited trial + fast sentencing; an early guilty plea.

**The precedent rule earned its keep immediately.** In the same rescan it
killed two more confident "monsters": (a) the OpenAI **(LOW)** valuation
markets, whose descriptions are a verbatim copy of the (HIGH) template
("reaches or exceeds"), which would make LOW-$600B already-true at an 0.08 ask
— but across the identical template family (Anduril/Stripe/ByteDance/Kraken/
Perplexity/Epic) the HIGHEST rung settles YES while lower rungs stay open and
cheap, i.e. UMA resolves it on intent; and (b) NATO×Russia "clash", whose text
counts non-munition UAV shootdowns — refuted because the June-30 sibling
settled **NO** despite the June 8 Latvia shootdown.
**Also confirmed: gamma's `liq` overstates executable depth by 20-50x**
(one market showed $10,285 `liq` vs $53 real at the touch). Always size off
`/book`, never off `liq`.
