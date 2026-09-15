# RETEST.md — re-opening the closed list under bugs #45/#46, measured fill rates, and 30 days

**2026-09-15. Read-only. Nothing deployed, nothing proposed for deployment.**
Author: quant lane. Parallel lanes: ml-engineer (`MODELS.md`), portfolio sizing, venue mechanics.

---

## PART 0 — PRE-REGISTRATION (written before any cell result in this document existed)

### 0.1 Instruments

| id | dataset | n | span | what it can answer | what it cannot |
|---|---|---|---|---|---|
| **I1** | `data/fills.parquet` | **8,496 attempts**, 4,434 matched, 4,390 with settled `net` | 08-17 → 09-14, **29 UTC days**, 7 coins | real dollars, real fill rates, real fees — **no fill model anywhere** | only covers the region the fleet actually fired in |
| **I2** | `data/evals_live.parquet` + `data/bars_live.parquet` | **53,898 bars** (50,190 on live coin-days) | 08-16 → 09-14, **30 days** | the decision-time census at tl≈27.9: est, side, displayed ask, `fire`, outcome — incl. bars the fleet never touched | ⚠️ `ask` is **oracle-conditioned** (recorded on the estimator's own side) ⇒ unusable for market calibration; and it is **one snapshot**, not the fire instant |

**I2 fidelity check, run before any hypothesis (this is a caveat I am promoting to a number):**
on live coin-days, `fire=True` at tl 28 is followed by an actual attempt on the bar only
**47.7%** of the time, and **61%** of bars that did get an attempt had `fire=False` at tl 28.
`evals_live` is therefore a **book-state census**, not the fleet's decision record. Every
dollar verdict below runs on **I1**. I2 is used only where I1 has no coverage (silenced coins,
never-fired cells) and its output is labelled as a **counterfactual with a fill model**.

### 0.2 Unit of analysis

The unit is the **ATTEMPT**, not the fill. `net = 0` for an unmatched attempt. This is the only
specification that does not need a fill model: a gate on an ex-ante observable (`seen_ask`, `tl`,
`est`, coin, hour) changes the attempt set, and the measured fill rate falls out of the data
automatically. Gate tests may use **only** ex-ante observables. `avg_px` is realised and is used
for description, never for a gate.

### 0.3 Scoring rule — and a correction to it

The standing rule is "drop fills where `req_px − avg_px ≥ 0.005`". **As literally written it is
mis-specified on this ledger** and I am not using it in that form. The bot's own buffer is
`req_px = seen_ask + 0.01` on 2,513 of 4,390 fills, so `req_px − avg_px ≥ 0.005` fires on every
ordinary at-the-ask fill: it drops **2,037 fills carrying $152.18 of the $242.79**, which is not
"the dislocation harvest", it is most of the book.

The quantity the rule is reaching for is **sweep depth = `seen_ask − avg_px`**, which is buffer-free.
At `≥ 0.005` that isolates **294 fills carrying +$107.89 (44% of net)** — which reproduces the
archive's "sweeps are 3.8% of bars, 44% of gross". **Every headline below is reported twice:
all-attempts, and ex-sweep (`seen_ask − avg_px < 0.005`).** A candidate that only works on the
sweep subset is re-describing the dislocation harvest and is rejected.

### 0.4 Concentration guard (pre-registered veto)

Reproduced independently here: top-1 fill **+$74.82 = 30.8%** of the 29-day net; top-5 **+$195.20
= 80.4%**. **Any candidate rule that would have deleted a top-5 fill is rejected on the spot**,
whatever its mean, because its mean is then a lottery on five events. Stated per candidate.

### 0.5 Statistics and the multiple-comparison budget

- Headline SE: **day-clustered** (G = 29 UTC days), reported as `t_day`. Bar-clustered and
  coin-day-clustered printed as sensitivity; the **max** SE is the headline.
- **LOO-day** (29 folds) and **LOO-coin** (7 folds) reported on **everything**, unprompted.
- Cell count declared up front: **H1 4 cells, H2 3, H3 5, H4 2, H5 ~18, H6 3 = 35 tests.**
  Bonferroni at α=0.05 ⇒ per-cell **p ≤ 0.00143 ⇒ |t| ≥ 3.19**. I will also report BH-FDR.
- **Context for every number below:** the fleet's own 29-day net is `t_day = 1.25`. **"Not
  significant" is the default state of this venue.** I will say so rather than manufacture
  confidence, and a cell that merely fails to reject is *not* evidence the cell is flat.

### 0.6 The hypotheses and their kill conditions — fixed before the run

| # | Hypothesis (the claim being re-opened) | Why it is re-openable at all | Cells | **KILL if** |
|---|---|---|---|---|
| **H1** | §38 buy-the-dip / cheap displayed ask (`seen_ask < 0.90`) is positive and was killed on day-concentration | killed on 15 wins / one day (08-13) and on an interpolated 11% fill rate for ≤0.75; the fill rate is now measured at 17.3% / 22.0% | seen_ask bands `<0.75`, `0.75-0.90`, `0.90-0.98`, `≥0.98` | per-attempt net is not > 0 at `t_day ≥ 3.19`, **or** the sign flips on any LOO-day or LOO-coin fold, **or** it survives only with the sweep subset included |
| **H2** | the `0.90-0.98` bleed band is a **veto** candidate | claimed a bleed on 08-30 (1 era), claimed *inverted* on 09-10 (10 days); never run on 29 | same 4 bands, judged as a deletion | vetoing the band is not > 0 at `t_day ≥ 3.19`, or it deletes a top-5 fill, or LOO-unstable |
| **H3** | the `tl 20-25` cell / the tl gradient (`tl ≤ 12` "shift the budget") | closed on "zero clips above tl 20" in a 10-day window that post-dates the §37 delay gate; the 29-day ledger does contain tl > 20 | tl `≤12`, `12-16`, `16-20`, `20-25`, `25-30` | no monotone gradient, or LOO-unstable, or the winning cell does not clear Bonferroni |
| **H4** | UP/DOWN asymmetry (+$235 vs −$148 on the 08-30 era) | refuted on 10 days at diff t=0.26; 29 days is 3× the day-clusters | UP, DOWN | `\|t_day\|` on the difference < 3.19, or LOO-unstable |
| **H5** | **selection** — a rule that says *when not to fire at all* (coin, UTC hour, ambient vol, book state at tl 28) | never run on 30 days with `fire` observable on every bar | 7 coins + 6 hour blocks + 3 vol terciles + 2 book-state = ~18 | deletes a top-5 fill (automatic reject), or fails Bonferroni, or LOO-unstable |
| **H6** | the fleet's **existing** silence (eth/xrp off since 09-10, hype since 09-13) has been good | directly observable on I2 | 3 coins | — descriptive; report the counterfactual dollars with its fill model stated |

### 0.7 What I expect, stated in advance so I cannot claim it afterwards

I expect **H1, H2, H4 to die and H3 to be a population effect, not a gate**. The one I think has a
real chance is **H5 by coin**, because the two coins the fleet has already silenced (doge, xrp are
the two negative-net coins in the ledger) look like the only cut with a mechanism behind it
(tick coarseness / book width), and because the fleet has *already* acted on it. If H5-by-coin
survives I will attack it with the concentration guard first, not last.

---

## PART 1 — TRIAGE OF THE CLOSED LIST (`winner-vacuum/docs/README.md`, all 81 decision rows)

### 1.1 Closed by identity or arithmetic — data quality cannot touch these. One line each.

| Row | Why it cannot re-open |
|---|---|
| Pair arbitrage (buy UP+DOWN < $1) | `ua ≡ 1−db` at 100.0000% over 1,966,903 event-exact pairs ⇒ `ua+da ≡ 1+spread` **algebraically**. 0 of 1,942,072 states below $1. |
| Mint-and-sell / mint-as-completing-leg / mint+merge exits | `−q−1+a+1 = a−q`: the mint is a cash no-op. Selling UP at *a* is bit-identically the queue "buy DOWN at 1−*a*". |
| Maker one leg + taker the other | UP bid + DOWN ask = exactly 1.000 by the same identity ⇒ gross zero by construction, then −1.40 c/sh of fee net of rebate. |
| A3b cost > mispricing bound (whole mid-bar family) | miscalibration 1-3 c/sh vs half-spread 1.0-2.2 + fee 0.3-1.75 in **every** band at **every** τ; maker mirror already −4.6 c/sh. |
| The direction 2×2 ("buy a side cheap, expect reversal") | collapses to one primitive by the one-book identity — it **is** the refuted cell, not a variant of it. |
| Cutting losses after entry / stop-loss | `ub ≡ 1 − da`: exiting the favourite at bid *q* is priced identically to buying the dog at ask 1−*q*. |
| Neg-risk arb (`sum(ask)<1`) | incomplete-outcome-set artefact. |
| Volume-tier **maker** rebate | `rebateRate` varies by market, never by our volume — verified live on the schedule. |
| Settlement is an average ⇒ digital is tighter | Var(TWAP)/Var(endpoint) 0.88-0.94, ~constant in τ. A ~10% variance cut, not a 42.33 s offset. Arithmetic of the estimator, not of the data. |
| A maker can never sweep | a resting order cannot cross. Structural. |

**Verdict: 10 rows stay closed permanently. Not re-run.**

### 1.2 Closed on evidence that is now suspect — RE-RUN. (Parts 2-4.)

| Row | Why suspect | Re-run as |
|---|---|---|
| §38 buy-the-dip / cheap displayed ask | 15 wins on one day (08-13); the ≤0.75 fill rate was an **interpolated 11%**, now measured 17.3% | **H1** |
| the 0.90-0.98 "bleed band" | claimed on one era (08-30), claimed inverted on 10 days (09-10) | **H2** |
| the tl 20-25 cell / tl gradient | closed in a 10-day post-§37 window with almost no tl>20 mass | **H3** |
| UP/DOWN asymmetry | refuted at diff t=0.26 on 10 days | **H4** |
| `vacmaker-analytics-leads` LOO-pending: 04-08 UTC hole, UP/DOWN asym, 0.90-0.98, tl 20-25 | never run on 29-30 day-clusters | **H2/H3/H4/H5b** |
| the vol gate (§34/§37) | keyed on a variable §33 said was the wrong one | **H5 vol arm** |

### 1.3 Leave closed — re-running would not change the verdict, and I am saying so rather than spending the budget.

Every **maker/resting** row (47 mid-band cells, rebate farm, tick-jump, ladder entry, signal-cancel, deep static bid, imb0 gate, openmm, poolfarm 5m/15m/1h, rewfarm, pre-open MM, mint+ask ladders, inventory-skew MM). They were not killed by estimator quality or by fill-rate interpolation — they were killed by a **measured** −4.6 c/sh terminal cost on 47,038 real fills, which bug #45 does not touch and a better `est` cannot pay for (§33's π-sweep: a *perfect* predictor is worth +36 c/sh maker, but the measured realistic edge is +1.17 ± 0.55 pp against a +3.03 pp break-even — rejected at 3.4 SE, not merely uncertified).
Also stays closed: leaderboard copying (fee 1.7× the gross edge), cross-coin/cross-duration lead-lag (A4: the bound never binds, median gap −0.320), reversion/1c-insurance (376k obs, no estimator involved), the latency/nowcast lane (a perfect zero-lag oracle flips 1 gated bar in 16 days), the ML direction predictor (mid AUC 0.8493, no model beat it — and bug #45 made the *panel* quieter and **better** than the bot, so the bar it failed to clear was, if anything, too easy).

---

## PART 2 — THE RE-RUN (I1, 8,452 attempts, 4,390 fills, 29 UTC days, +$242.79)

Baseline reproduces the fleet exactly: **+$242.79, t_day 1.25**, top-1 30.8%, top-5 80.4%.
All five top-5 fills listed once here because every candidate below is judged against them:

| # | coin | day | tl | seen_ask | avg_px | net |
|---|---|---|---|---|---|---|
| 1 | bnb | 09-06 | 11.7 | 0.99 | 0.238 | +74.82 |
| 2 | btc | 08-25 | 16.3 | 0.99 | 0.190 | +33.32 |
| 3 | sol | 09-02 | 13.4 | 0.63 | 0.342 | +31.28 |
| 4 | btc | 09-12 | 19.7 | 0.67 | 0.370 | +29.32 |
| 5 | sol | 09-02 | 10.9 | 0.55 | 0.349 | +26.46 |

### H1 — the cheap displayed ask (§38 buy-the-dip). **DEAD ON THE PRE-REGISTERED KILL; positive but unprovable.**

| band | att | fills | fill rate | net | per att | ROI | t_day | top5 in |
|---|---|---|---|---|---|---|---|---|
| <0.75 | 457 | 80 | **0.175** | +109.58 | +0.2398 | +16.1% | **1.27** | 3 |
| 0.75-0.90 | 1113 | 253 | **0.227** | +47.51 | +0.0427 | +1.8% | 0.41 | 0 |
| 0.90-0.98 | 1862 | 965 | 0.518 | −156.51 | −0.0841 | −1.8% | −2.05 | 0 |
| ≥0.98 | 5020 | 3092 | 0.616 | +242.22 | +0.0483 | +0.6% | 1.71 | 2 |

The measured fill rates **reproduce the brief's 0.173 / 0.220 / 0.512 / 0.749 to within 0.003** — bug #23's old 11% interpolation is gone and the cheap band really does fill 17.5%.
LOO is clean: `<0.75` has **0 sign flips over 29 days and 0 over 7 coins** (worst fold +47.53 ex-sol).
But **t_day = 1.27 against a pre-registered bar of 3.19**, and **3 of the top 5 fills live in it** — ex-sweep the band is +43.79 at t 0.92. Kill condition met on both clauses.
**Verdict: the cheap lane is real, already live (`MIN_ASK=0.55`), and cannot be sized up on this evidence. Nothing to change.** It would need ~7× the sample.

### H2 — the 0.90-0.98 bleed band. **THE VETO IS ALREADY DEPLOYED, AND ITS ONE CONTROL ARM IS WINNING.**

Raw, the band is the most robustly negative cell in the ledger: **−$156.51, 0 LOO-day sign flips (25 folds), 0 LOO-coin sign flips, 0 top-5 fills.** t_day −2.05, day-bootstrap on the veto `[+17.6, +316.5]`, P(>0)=0.989. That is what a real lever looks like — and it is still **not deployable**, for three independent reasons found only by going and looking:

**(a) It was shipped on 2026-08-31.** `PM_TE_FIRST_SKIP_LO=0.90 / _HI=0.98` is live in the pods *right now*. First-clip attempts in the band go to zero on 08-31 for six coins in a single step (08-28: bnb 19, doge 24, hype 25, sol 10, xrp 9 → 08-31 onward: 0, 0, 0, 0, 0).

**(b) `eth` was missed and is therefore an accidental 10-day control arm — and it is positive.** `PM_TE_FIRST_SKIP_HI=0` on the eth pod alone. eth kept firing first clips in the band: **223 attempts / 40 fills / +$15.43 / exactly 1 losing fill**, 08-31→09-09. Its own pre-08-31 history in the same cell: 221 attempts / 70 fills / **+$27.88 / 1 loss**. Pooled, eth's first-clip band cell is **+$43.31 over 444 attempts with 2 losses** — the LOO-coin fold confirms it (removing eth takes the pooled clip-1 cell from −81.56 to **−124.87**). One coin, and P(0-or-1 loss | 40 fills, 4% loss rate) ≈ 0.52, so this is **not** evidence the skip is wrong. It **is** evidence the pooled cell is not homogeneous and the veto is a coin-level bet.

**(c) Forward, the lane is gone.** Attempt mix by era: 0.90-0.98 was **25.4%** of attempts at 400 attempts/day through 09-03; it is **2.6%** of 113/day since. In the last 11 days the band is **+$30.01 over 32 attempts, positive on all 7 days it occurred**. Whatever the veto was worth, it is now worth ~$0/day.

The residual is **ladder clips 2+** (`WHALE_LADDER_MIN_ASK=0.94` still lets them through): −$74.95, t_day −1.89, 0 LOO sign flips either way, 0 top-5. Raising that gate to 0.98 scores **+$74.95 over 29 days at t_day 1.86, 11/29 days improved, worst day 1.2c worse**. It fails Bonferroni, and the lane is now **0.4 attempts/day** — post-08-31 it is **+$16.00 over 17 attempts**. **Do not ship it. The forward value is under $1/day and the sign has already flipped on the fresh sample.**

### H3 — the tl gradient / the tl 20-25 cell. **A POPULATION EFFECT AND AN ERA, NOT A GATE.**

| tl | att | fills | net | per att | ex-sweep per att | t_day | days present |
|---|---|---|---|---|---|---|---|
| ≤12 | 1879 | 235 | +152.82 | +0.0813 | +0.0210 | 1.64 | 27 |
| 12-16 | 1219 | 570 | +58.95 | +0.0484 | +0.0271 | 0.90 | 29 |
| 16-20 | 3263 | 2181 | +137.65 | +0.0422 | +0.0404 | 0.84 | 29 |
| 20-25 | 1025 | 610 | −4.67 | −0.0046 | −0.0184 | −0.08 | 29 |
| 25-30 | 1066 | 794 | −101.95 | −0.0956 | −0.0432 | −2.32 | **6** |

The gradient is monotone — and the only decisive cell, tl 25-30, exists on **6 days**, all of them before the §37 delay gate went live on 08-22. **It re-derives a fix that shipped three weeks ago.** tl 20-25 is noise by its own kill condition: **5 sign flips of 29 LOO-day folds and 3 of 7 LOO-coin folds.** The `tl≤12` cell is positive but collapses +152.82 → +38.94 ex-sweep and holds 2 top-5 fills. **Verdict: no change to the fire window, in either direction. H3 closed, and it stays closed.**

### H4 — UP/DOWN asymmetry. **DEAD. And it is 4-of-7-coins inconsistent.**

UP +$378.90 (t_day 2.41) vs DOWN −$136.11 (t_day −0.94); **difference t_day = 2.22 over 29 day-clusters** vs the pre-registered 3.19. Ex-sweep: UP +197.33, DOWN −62.43.
The kill is not only the t. Per coin, **DOWN is non-negative on bnb, btc, eth and xrp** and negative only on doge, hype, sol; UP is negative on doge, eth, xrp. There is no coin on which the story holds in both legs. All 5 top-5 fills are UP, so a DOWN-veto does not delete the fat tail — it is a clean rule, it just has **no mechanism** and would be a directional bet on Aug-Sep 2026 crypto drift. **Verdict: dead, as the archive said.**

---

## PART 3 — TASK 2: WHEN SHOULD WE NOT FIRE AT ALL?

Full veto ledger, all rules judged the same way (baseline +$242.79, worst day −$74.56):

| rule | keeps | net | Δ | t_day | days improved | worst day | top-5 deleted |
|---|---|---|---|---|---|---|---|
| veto ask 0.90-0.98 | 6590 | +399.30 | +156.51 | 2.03 | 11/29 | **−81.10 (worse)** | 0 |
| veto 08-12 UTC | 6913 | +382.03 | +139.24 | 1.52 | 10/29 | −32.79 | **1** |
| veto doge + xrp | 5614 | +393.07 | +150.28 | 1.66 | 16/29 | **−79.65 (worse)** | 0 |
| veto DOWN | 4210 | +378.90 | +136.11 | 0.94 | 15/29 | −53.43 | 0 |
| veto tl > 20 | 6838 | +339.72 | +96.93 | 1.47 | **5/29** | −74.56 | 0 |
| fire ONLY 16-20 UTC | 1260 | +249.19 | **+6.40** | 0.04 | 12/29 | −19.71 | **2** |

**Nothing clears 3.19. Nothing clears 2.5.** That is the honest headline, and at this size it is the expected result, not a failure of the search.

**By coin (the one I pre-registered as most likely to survive): REJECTED, and both losers are single days.**
doge −$90.66 — but the LOO-day best fold is **−$16.23**, i.e. **82% of doge's entire loss is 09-02 alone**. xrp −$59.61 — best fold **−$16.67**: **72% is 08-31 alone.** These are the exact fingerprint the archive warns about (09-09 was −$70 of a −$76 "trap band"). Both coin vetoes also make the **worst day worse**. **Reject. There is no coin to switch off.**

**By UTC hour.** 16-20 UTC is the only cell in the whole document that touches the Bonferroni line: **+$249.19, t_day 3.26, t_coin-day 3.36, 0 LOO sign flips on 29 days and 0 on 7 coins, 23/29 days positive, 6 of 7 coins positive.** It dies on the pre-registered concentration guard the moment it is made tradeable: it holds **3 of the top 5 fills**, so ex-top-5 t falls to 2.55 and **ex-sweep to 1.80**, and "fire only 16-20" **deletes 2 top-5 fills for +$6.40**. The mirror veto (08-12 UTC, −$139.24) reaches only t −1.52 and deletes a top-5 fill. **The hour is where the sweeps happened, not a rule.** It is also *not* the old 03-11 hole restated, and not the mid-band: excluding 0.90-0.98 entirely, 16-20 is still +$240.41 and 08-12 still −$94.86.

**By ambient vol (`_ambient_vol` joined from `PF_TE_WHALE_DELAY`, 58.2% of attempts).** lo +$198.37 / mid +$100.03 / **hi −$11.54**. Monotone, and the decisive cell is **t −0.14 with 6 sign flips of 25 LOO-day folds**. **The §37 decision to strip the vol condition is re-confirmed on 29 days: vol is not the discriminator.**

**By conviction (`|est|` terciles, ex-ante).** low +$171.19, mid +$89.32, high −$17.72 at t −0.32 — and the high tercile fills only **10.5%** of the time, because a decisive estimate and a takeable ask do not co-occur. **No conviction floor, re-confirmed. There is no "fire harder when sure" lever, because the book is not there when we are sure.**

**Ladder clips.** Clip 1 is the whole book. This reproduces the brief and needs no new cell.

### ⭐ THE ANSWER TO TASK 2 IS NOT A GATE — IT IS THAT THE FLEET IS SILENTLY BROKEN

**eth and xrp have not placed an order since 2026-09-09 19:59 UTC. That is not selection. It is a bug, and I have the mechanism, the arithmetic and the confirming natural experiment.**

Both pods are `Running`, WS `ready=True`, balance $466.96, presigning two orders every bar, and still emitting 30-58 `PF_TE_WHALE_DELAY` decisions per day with takeable asks and decisive estimates (e.g. xrp 09-14: ask 0.85, est +12.196 bps). They simply never fire. `_whale_fire()` has exactly **two silent returns** — `_risk_halted()` and the inflight cap:

* `risk-state.json` on the pods rules out the halt: eth `halt_until` is in the past, xrp `halt_until = 0.0`.
* So it is `if self.live_inflight + sh * ask > LIVE_INFLIGHT_CAP: return` — **which logs nothing** (the two sibling call sites at lines 446/522 *do* emit an event; this one does not).

**Root cause — `twapedge.py settle_loop`, the abandoned-settle path:**
```python
if up is None:
    if now > ws + BAR_SECONDS + 900:
        bar.settled = True                      # <-- live_inflight never decremented
        if bar.whale or (bar.live and bar.live.get("filled")):
            _event("PF_TE_SETTLE_ABANDONED", ...)
    continue
```
The position is real and the sweeper redeems it, but the in-memory `live_inflight` reservation is **never returned**. It is a **one-way ratchet against a $60 cap that only a pod restart clears.**

A Gamma outage on **2026-09-09 19:00-20:30 UTC** hit the whole fleet. `PF_TE_SETTLE_ABANDONED` events, and the leak measured from each pod's own archives since its exact container start:

| coin | container start | leaked | cap | headroom | min possible clip (26 sh × 0.55) | status |
|---|---|---|---|---|---|---|
| **eth** | 08-31 13:17 | **$47.52** (09-09 19:05, 19:55) | $60 | **$12.48** | $14.30 | **permanently dead** |
| **xrp** | 09-01 13:54 | **$47.52** (09-09 19:15, 19:55) | $60 | **$12.48** | $14.30 | **permanently dead** |
| **hype** | 08-31 13:18 | **$44.46** (09-09 22:35, 09-10 00:35) | $60 | **$15.54** | $14.30 | crippled: can only fire at **ask ≤ 0.598** |
| doge | 09-03 15:57 | $14.85 | $60 | $45.15 | $2.75 ($5 clips) | degraded 25% |
| bnb | 08-31 13:17 | $0.00 | $60 | $60 | — | healthy |
| btc | **09-14 04:39 (restart)** | $0.00 | $60 | $60 | — | healthy *by accident* |
| sol | **09-13 11:46 (restart)** | $0.00 | $60 | $60 | — | healthy *by accident* |

**The hype row is the confirming experiment I did not have to design.** With $15.54 of headroom it can fire only when `26 × ask ≤ 15.54`, i.e. **ask ≤ 0.598**. It has fired twice in six days, and the one I can read in full is **2026-09-15 19:39 UTC at `seen_ask=0.59`, `req_sh=26` = $15.34** — inside the predicted ceiling by 20 cents. That is a point prediction from the leak arithmetic, confirmed on live tape.

**What the silence has cost.** I will not quote a dollar counterfactual, because the only fill model available for it **reads the sign backwards**: applied to the four coins that *kept* trading over the same 5 days it scores −$49.53 against an actual **+$56.22**. This is bug #46 again (snapshot ask, share-denominated, sweeps deleted) and it is exactly why no replay number belongs here. What is measurable:
* the opportunity set is intact — **402 gated eth/xrp/hype decisions in 5 days, 98.0% side-correct**, 62 of them at ask < 0.90 (the fleet's profit centre);
* on their own 29-day ledger rates the three coins are eth +$0.72/day, hype +$0.57/day, **xrp −$2.48/day** ⇒ restoring them is worth **−$1.19/day** naively and **+$0.57/day** once xrp's single −$42.94 day (08-31) is removed. **Statistically indistinguishable from zero either way.**

**So the verdict is not "turn them back on because it is worth $X".** It is:
1. **The fleet is losing coins to a ratchet.** bnb is one abandoned bar from the same fate; btc and sol are only alive because they happened to restart. On the current rate (7 abandoned bars across 7 coins in 29 days) the expected time to a fully silent fleet is months, not years, and **every step of it is invisible** — no event, no alert, no log line.
2. **Any future analysis that reads "the fleet chose not to fire" is contaminated.** The brief's "free natural experiment" does not exist. I would have written it up as a selection finding had I not gone to the pods.
3. The instrument must be repaired before the selection question can be asked at all. **That is an operator decision and I am not proposing a deploy** — but note that the repair is two independent things: returning `live_inflight` on the abandoned path (a code fix), and clearing the three latched pods (a restart).
4. Separately: **`PM_TE_FIRST_SKIP_HI=0` on eth alone** is config drift from the same 08-31 deploy. It is the only reason H2 has a control arm at all.

---

## PART 4 — THE TAKER-FEE COMPOSITION (answered with the venue lane; **nothing re-opens**)

My fee decomposition reconciles with the venue agent's independent measurement ($127.20 across my 29-day attempt set vs their $134.00 across 30 days). Their result is that the tier ladder is algebraically a fee-spend ladder (`wV ≡ 32.857 × fee`), that Obsidian is 45× our spend away, that the taker rebate accrues **$0**, and that the rate went 0.0312 → 0.07 since Feb. So the question is not "which verdict reopens at a lower rate" but "which verdict was a fee artefact at all". **Answer: none of mine.**

| cell | net | fee paid | net @ half fee | net @ **zero** fee | reopens? |
|---|---|---|---|---|---|
| ask < 0.75 | +109.58 | 18.08 | +118.62 | +127.66 | no — t_day 1.27 → ~1.3; the bar is 3.19 |
| ask 0.75-0.90 | +47.51 | 35.83 | +65.42 | +83.34 | no — biggest *relative* gain (+75%) but t 0.41 |
| **ask 0.90-0.98** | **−156.51** | 28.45 | −142.28 | **−128.06** | **no — still deeply negative with the fee removed entirely** |
| ask ≥ 0.98 | +242.22 | 44.84 | +264.64 | +287.06 | n/a (already live) |
| doge | −90.66 | 11.85 | −84.74 | −78.81 | no |
| xrp | −59.61 | 19.94 | −49.64 | −39.67 | no |
| 08-12 UTC | −139.24 | 19.15 | −129.66 | −120.08 | no |
| DOWN side | −136.11 | 63.02 | −104.60 | **−73.08** | no (and DOWN pays half the fleet's entire fee) |

Two things worth carrying:
* **Mean fee per fill by band: 22.6c at <0.75, 14.2c at 0.75-0.90, 2.9c at 0.90-0.98, 1.5c at ≥0.98.** The venue agent's reframing is right and it is visible in our own ledger — the fee is a tax on uncertainty. Our realised effective cost is **0.234 c/share**, not 1.75. **The "cost exceeds mispricing in every band" bound (A3b) is a mid-band statement; the live lane pays 7.5× less than the framing implies.** It does not rescue any cell above, but it means the *cheap* bands (which pay 10-15× more fee per fill than the 0.99 lane) are the ones where a fee change would ever have mattered — and even zeroing it does not move their t.
* **Total fee is 34% of gross profit** ($369.99 gross → $242.79 net). A fee cut is the single largest non-strategy lever on this book — and per the venue lane it is unavailable in both directions, so it should be treated as a fixed cost and the **direction of travel is against us.**

---

## PART 5 — VERDICT

**No new strategy. No gate. One live defect that matters more than every cell in this document.**

1. **Nothing in the re-run clears its pre-registered bar**, and at 29 day-clusters against a baseline that is itself only t=1.25, that is the expected outcome. I ran ~34 tests; the largest |t| anywhere is 3.36, against an expected max-under-null of roughly 2.8-3.0 for a family this size, and that one cell fails the concentration guard. **I am reporting "not significant" rather than dressing 16-20 UTC up as a finding.**
2. **H1 (cheap ask) is positive, LOO-clean in both dimensions, and unprovable** at t 1.27. It is already the live lane. It needs ~7× the sample, i.e. months.
3. **H2's veto shipped on 08-31** and its forward value is now ~$0/day (2.6% of attempts, +$30 over the last 11 days). Its only control arm (eth, by accident) is positive. **The ladder extension to 0.98 is +$75/29d at t 1.86 on a lane that now sees 0.4 attempts/day — not worth the risk of a config change.**
4. **H3 and H4 stay closed**, and H3's decisive cell is a pre-08-22 era that the §37 gate already removed.
5. **The two coin-level "losers" are each one day.** There is no coin to switch off.
6. **`eth` and `xrp` are silently dead and `hype` is crippled, from an inflight ratchet on the abandoned-settle path.** Cost to date is indistinguishable from zero; the exposure is that the ratchet takes coins permanently, invisibly, and one at a time. **This is the finding of the session.**
7. **No verdict re-opens at a lower taker rate.** Every negative cell is still negative with the fee set to exactly zero.

**Confidence.** Items 1-5 are as certain as 29 day-clusters allow, which is to say the effects are bounded by roughly ±$5/day and I cannot distinguish any of them from zero. Item 6 is not statistical — the leak is arithmetic, measured on each pod's own archives, and independently confirmed by hype's $15.54 headroom predicting its 0.59-ask fire. I would attach >95% confidence to the mechanism and ~0% to any dollar figure for what the outage has cost.
