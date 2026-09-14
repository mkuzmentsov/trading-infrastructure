# Overnight multi-agent strategy hunt — 2026-09-14. 24 candidates, 0 deployable. The real output is a correction to what we believe about our OWN bot.

User asked for an overnight hunt with role-specialised agents (investor, bettor,
mathematician, validator, researcher, docs expert, crypto expert), 5m crypto only.
Ran as a workflow: **37 agents** — 6 specialist generators in parallel → 24
candidates → top 10 each attacked by 3 adversarial validators with distinct
lenses (data validity / execution feasibility / economics) → synthesis.
4.16M subagent tokens, 1,185 tool calls, ~64 min. Zero agent errors.

## ⭐⭐ THE HEADLINE IS ABOUT US, NOT THE MARKET

The synthesis rebuilt the full live ledger (8,441 `PF_TE_WHALE_ORDER`, 4,388
matched, 4,346 joined to settles, 08-17 → 09-14, $50,694 staked):

| | |
|---|---|
| Gross PnL | +$356.80 |
| Modelled taker fee (0.07·p·(1−p)·sh) — **the ledger never charged it** | −$124.53 |
| **Net, 29 days** | **+$232.27 = $8.01/day** (not the ~$19/day we have been quoting) |
| Win rate | 96.57% (4,197W / 149L) |
| Day-clustered t | **1.84 gross, 1.20 net** |
| Same-price Poisson-binomial null on wins | obs 4,197 vs exp 4,178.6, **z = +1.57** |
| Top-5 fills | **$195.20 = 84% of net** |
| **Ex-top-5** | **+$37.07 / 29 days = $1.28/day** |

**The fleet's edge is not statistically distinguishable from zero, and 84% of it
is five order-book dislocations arriving 0.17×/day.** Every proposal in this hunt
was competing against a baseline that is itself unproven. Reaching a day-clustered
t=2 on the current fleet takes **~80 more days**.

⚠️ Caveats the synthesis stated: eth/xrp ledgers stop 09-09 (log rotation) so the
last five days are 5 coins; the fee is modelled from the published formula, not
receipts; `disloc` is populated on only 2,126 of 4,346 fills.

## What the money actually is (decomposition — all verified)
- Fills printing **≥0.5c below the requested limit** ("sweeps"): n=2,019 (46.5%) → **+$151.30 = 65% of net**
- Dollar-denominated FAK buying **more shares than requested**: n=125 → +$56.61 = 24%
- Fills printing **below 0.90**: n=365 (8.4%) → **+$219.40 = 94% of net**, win rate only 81.1%
- Of those, **27 were requested against a seen_ask of 0.95-1.00** → +$74.62: the displayed ask was ~0.99 and the book behind it was hollow.

⭐ **New operator rule for the bug ledger:** *before scoring any candidate, drop
fills where `req_px − avg_px ≥ 0.005`. If its edge disappears, it is not a
candidate — it is re-describing the dislocation harvest the dollar-denominated
FAK already performs by design.* On this ledger that trim removes $151 of $232.
Three separate candidates ("the tl≤14 lane", "the cheap-ask lane", "sweeps") were
the same dollar wearing different hats.

## The two survivors — both NEGATIVES that close expensive directions

**1. No venue tape / latency work can sharpen the estimate. CEILING MEASURED.**
A *perfect zero-lag Chainlink oracle* — the strict upper bound on any Binance/HL
nowcast, since no nowcast sees future ticks — was replayed on cl+panel+barrecon
(08-25→09-10, 7 coins, n=10,756 bars/tl):

| tl | relay → oracle | McNemar W/L | under the live gate |
|---|---|---|---|
| 12 | 0.9867 → 0.9879 | 13/0 | n=687, **0 flips** |
| 20 | 0.9765 → 0.9781 | 17/0 | n=1,257, **1 flip** |
| 30 | 0.9642 → 0.9652 | 12/1 | n=2,018, **0 flips** |

**One flipped tradeable bar in 16 days ≈ $0.67/day of perfect clairvoyance about
the past**, against an $8/day bot. And the *why*: at tl=20 the relay-lagged
estimator is side-wrong on 110/1,257 gated bars; full-bar truth (impossible
clairvoyance about the *future*) fixes **83**, the zero-lag oracle fixes **1**.
**~99% of gated decision error is unobserved future ticks, not relay lag.**
⇒ Do not fund latency work, a Binance nowcast, co-location, or a basis model.
Two corrections to the candidate's own reasoning: CL/Binance showed **zero**
disagreements at |margin|≥1bps (n=729); and depth20 top-5 imbalance **is** real
signal vs the residual (partials +0.14…+0.38, p<1e-4, all 6 coins) — it is just
~0.06 bps against a 4.9 bps median |est|. Close it as *"0.06 bps, unbuyable"*,
not as *"no signal"*.

**2. Keep the flat $24 clip. Kelly / edge-proportional / price-proportional
sizing all refuted.** Every variant's advantage lives in the same 5 fills, and
those fills are invisible at decision time — two of the five had `seen_ask=0.99`
and `est_bps<2.3`, so Kelly's decision-time weight on them is ~zero. A
tape-capped Kelly (real ladder depth + tape-confirmed prints) came in at
**−$14 to −$24** vs the flat clip's +$218, because only 32-40% of the wanted
dollars are obtainable.

## The most tempting near-miss, killed
**Excising the mid-band.** By decision-time `seen_ask` the 0.90-0.975 band shows
n=965, **−$156.51**, t_day=−2.05 — apparently a free $5.40/day. **It is an era
artifact**: pre-09-01 −$178.42 (15d), 09-01 onward **+$21.91** (10d). The band has
been *positive* for two weeks. With six bands searched, an unadjusted t of −2.05
driven entirely by the first half is nothing. **Do not excise the mid-band** —
and note this independently re-kills the same idea the 09-02 hunt flagged as an
"open lever", by a different route.

## REFUTED — never re-propose
| # | Idea | Why it died |
|---|---|---|
| 1 | fee-adjusted 0.90-0.98 band edge | fee correction adopted; band edge era-bound (−$178 → +$22) |
| 2 | kill MIN_ASK=0.98 / excise 0.90-0.975 | era split + boundary instability + search-adjusted null |
| 3 | `deferExec=true` to stop SDK hash polling | mechanism does not exist — responses already carry the hashes |
| 4 | relay-gap (stale-displacement) veto | vetoes the wrong bars; margin, not staleness, discriminates |
| 5 | Binance-lead residual correction | headline evidence was look-ahead by 1s; real effect 0.06 bps |
| 6 | triple the tl≤14 clip, defund tl 14-18 | the lane's dollars ARE the dislocations; they cannot be tripled |
| 7 | leverage-corrected certainty gate (k/n envelope) | reproduces, then dies on the same 5-clip concentration |
| 8 | HYPE 3× liquidity / no-spot-feed angle | the 3× sits at 0.999 (EV 0.09c/sh); hype has the fleet's lowest fill rate |
| 9 | any Chainlink nowcast / latency / co-location | perfect-oracle ceiling $0.67/day |
| 10 | Kelly / edge- / price-proportional sizing | advantage = the same 5 unrepeatable fills; tape-capped Kelly negative |

## ⭐ TOOLING DEFECTS FOUND — BOTH FIXED THIS SESSION (`panel.py`)
`panel.parquet` underpins most replay research, and it had two defects:

**(a) Look-ahead.** `b = np.maximum(b, a+1)` forced the settlement window open
even when the relay had not reached its start, so rows at `tlk ≥ 63` averaged a
**future** tick (100% of them, median +1s, up to +28s). Verified across all
1,647,734 rows. **Fixed:** a decision made before the window opens now emits
`NaN`. Post-fix `tlk≥63` is 100% NaN (was 7% NaN ⇒ 93% contaminated).
⚠️ `tools/mrec/tickjump/lw3.py` filters `tlk.between(0,95)` and
`tools/mrec/midband/r3070/lw4.py` applies **no tlk filter** — both consumed
contaminated rows. They are now protected by the NaN, but any result they
produced before today is unlanded.

**(b) Wrong estimator.** `core/rtds.py:window_mean()` — what the bot actually
runs — **forward-fills** unpublished seconds from the last value. `panel.py`
averaged only *delivered* ticks. Different estimators. **Fixed:** panel now
forward-fills, matching the live definition; `obs`/`cov` still count real ticks.
Rebuilt: 63.8% of rows changed, median |Δ| 0.044 bps.
⚠️ **HONEST DISCREPANCY:** the validator reported the live estimator as *better*
(+0.91pp @tl12, +1.82pp @tl20). **I could not reproduce that.** Under my proxy
gate (|est|≥0.5, cov≥0.5, fav_ask≤0.99) accuracy moved slightly the *other* way:
tl12 92.39→91.55, tl20 90.32→89.38, tl30 90.22→90.02. My gate is a crude proxy
for the bot's real gate (which is time-scaled and has ladder rules), so this is
not decisive either way. The fix is justified by **fidelity to the live
estimator**, not by a measured accuracy gain. Do not quote the +0.91pp figure.

## The one open question worth data (NOT more pq-venue)
Stop expanding `pq-venue` for strategy purposes — its 10 hours already closed the
question it was collected for, and no additional Binance/HL tape raises a ceiling
set by *future* Chainlink ticks.

**The binding unknown: when a favourite's displayed ask is stale and the book
behind it is hollow, how many dollars were actually available?** That is where
84% of the money is and it is unmeasured — we log `seen_ask`/`req_px`/`avg_px`/
`filled` but **not the full ask ladder at fire time**, so we cannot tell whether
the bnb 09-06 event had $75 of headroom or $750.
**Proposed instrumentation (NOT deployed — touches a live bot, needs user
approval):** have `PF_TE_WHALE_ORDER` log the complete favourite ask ladder (all
levels + sizes) at decision time plus the full FAK fill breakdown. With ~30 days
of that, "how big can the sweep clip be" becomes a one-query answer — the only
lever with a plausible multiple on $8/day.
**Second ask, free: keep the fleet running unchanged.** One more day on the
denominator is the most valuable thing that happens tonight.
