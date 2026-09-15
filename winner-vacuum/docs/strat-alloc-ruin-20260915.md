> ⚠️⚠️ **THREE CONFIG CLAIMS IN THIS DOCUMENT ARE FALSE — verified against the repo and the live
> pods on 2026-09-15. The analysis stands; the §H1 halt proposal does not.**
>
> | claim in this doc | reality |
> |---|---|
> | "`PM_TE_FIRST_SKIP_LO/HI` is in **no values file** — never deployed" | ⛔ present in **13** values files; `btc_vacmaker.yaml` lines 43-44 carry `0.90`/`0.98`, and the live pod env matches |
> | "`pmTeRiskPersist` is in **no values file**" | ⛔ present in **14** values files; `btc_vacmaker.yaml` line 41 sets `"1"` |
> | "`PM_TE_RISK_PERSIST` defaults to 0 ⇒ **halt state wiped on every restart**" | ⛔ **`PM_TE_RISK_PERSIST=1` live** on btc/doge/sol, and `/app/logs/risk-state.json` is present and being written (904 B, Sep 15 20:40) |
>
> ⇒ **The §H1 proposal ("make the halt layer real") rests on a premise that is already true.** The
> separate observation that `liveMaxDailyLossUsd` is *smaller than one bar's p99 exposure*
> ($47.52 vs $30 ⇒ ~0.63 "lives", not the "2-losses-and-out" the config comment claims) was **not**
> checked here and may still hold — but it must be re-derived before anyone acts on it.
>
> Everything else below — the ruin table, the era reversal, the sizing null, the coin split-half,
> the sweep decomposition, the fee reconciliation — was independently spot-checked and **confirmed**.

# ALLOC.md — capital allocation, capacity and risk for the 5m taker fleet

**2026-09-15. Read-only. Nothing deployed, nothing proposed for deployment.**
Author: portfolio/risk lane. Parallel lanes: quant (`RETEST.md`), ml (`MODELS.md`), venue (`VENUE.md`).
Scripts: `research/out/alloc/a1..a13*.py`. Data: `research/data/fills.parquet` (8,496 attempts,
4,434 matched, 4,390 settled, 08-17→09-14, 29 UTC days, 7 coins). Fee charged by me on the **fill**
price as `filled · 0.07 · p_fill · (1−p_fill)`; reconciles to $128.93 / 0.23 c-share / mean
p(1−p)=0.0319, matching the venue lane's independent $134.00 / 0.234 / 0.0334 within the window
difference. **No rebate credited anywhere** (venue lane: ongoing accrual is $0).

---

## THE DECISION

**Change nothing about clip size. Change nothing about which coins run. Both questions are
below the noise floor, and the one piece of evidence that looked decisive reversed out of sample.**

The only defensible changes I found are two mechanical defects in the halt layer (§4), and they
are worth proposing precisely because **their judging metric is not PnL**.

Bankroll assumed: **$450**. The book is *not* capital-constrained — peak concurrent exposure across
all 7 coins in a single 5m window was **$142.44 (31.7% of equity)**, p99 **$71.28 (15.8%)**. Turnover
is 3.98× equity/day, but 5m settlement recycles it; the binding constraint is depth and bar supply,
never cash.

### The number that should drive the decision

| 144-day window (the time needed to learn whether $8.37/day ≠ 0) | k=0.5 | **k=1 (now)** | k=1.5 | k=2 |
|---|---|---|---|---|
| P(equity < $50) **if the true edge is zero** | 4.9% | **31.8%** | 49.9% | 60.2% |
| median max drawdown if edge is zero | $219 | **$440** | $658 | $875 |
| P(equity < $50) if the edge is as measured | 0.0% | **0.2%** | 1.7% | 4.1% |

t = 1.25 on 29 days **cannot reject zero**. So we are running at a size where, if the edge is not
real, there is roughly a **one-in-three chance of losing the account before we could have found out**.
That asymmetry — not growth-optimality — is the allocation problem.

---

## 1 — Clip sizing: hold. The $8-vs-$24 difference is undetectable, and over-requesting is free.

### 1.1 The framing in the brief needs one correction

"Mean realised clip is $14.34 — we are not using the cap we have" is not what the tape says. Request
sizes are **bimodal, not under-used**: p50 = $7.92, p90 = $23.76 on every coin. We fire the $8 base
FAK and the $24 ladder roughly half and half; $14.34 is the mixture mean. The cap *is* being used.

### 1.2 The controlled comparison finds nothing

Within `seen_ask ≥ 0.98`, clip 1, restricted to common-support strata (same coin, same displayed ask,
same tl bucket):

| | n | stake | net | $/fill | ROI |
|---|---|---|---|---|---|
| ~$8 request | 665 | $5,007 | +$64.12 | +0.0964 | +1.281% |
| ~$24 request | 1,077 | $22,874 | +$111.80 | +0.1038 | +0.489% |

Day-block bootstrap on the difference: **d($/fill) = +0.0074, 95% CI [−0.2306, +0.1842],
P(BIG > SML) = 0.530.** The ROI gap is directionally consistent (P(ROI_big > ROI_sml) = 0.18) but
$/day — the thing we actually care about — is a **coin flip**. 2.9× the capital bought no detectable
change in dollars earned per fill.

### 1.3 Why over-requesting is nevertheless safe — and why that settles the question

**The FAK price limit binds 100% of the time: 0.00% of 4,434 fills printed above their own `req_px`**
(mean `fpx − req_px` = −1.045c). The "17.8% of fills land above the displayed ask" in the brief is
the bot's own `+0.01` buffer, not slippage past our limit. So a larger request cannot walk us into a
worse price than we chose; it can only take more of what is already there at an acceptable price.

The book rations us automatically, and the completion ratio is the live depth measurement — it ranks
exactly with the measured top-of-book depth:

| coin | depth (median TOB $) | completion at ≥0.98 | ROI, ≥0.98 clip-1 |
|---|---|---|---|
| btc | 980 | 0.991 | +2.38% |
| eth | 160 | 0.985 | −0.37% |
| sol | 105 | 0.961 | +0.06% |
| doge | 92 | 0.953 (at $8) | −1.37% |
| xrp | 86 | 0.922 | +0.39% |
| bnb | 26 | 0.875 | +1.40% |
| hype | 15 | 0.784 | +0.84% |

Completion below 1.0 is **not a cost** — it is the book declining to sell us more at our limit.
Confirming this: the two worst-completion coins are the two where the big clip does *better*
(bnb BIG +1.44% vs SML +1.17%; hype BIG +1.22% vs SML −1.46%).

There is a genuine price cost to size — within `seen_ask = 0.98` exactly, a $24 request fills
**+11 to +34 bps worse** than an $8 one, consistently across all six coins with support. At p=0.98
the entire margin over break-even is ~44 bps, so 34 bps is material. But it is already inside the
measured $/fill, and the measured $/fill difference is zero.

### 1.4 Per-coin clip: unchanged

| coin | current clip / ladder | verdict |
|---|---|---|
| btc, eth, sol, xrp, bnb, hype | $24 / $48 | **hold** |
| doge | $5 / $4 | **hold** |

**Do not raise.** No measurable return (§1.2); no fee-tier unlock to reward scale (venue lane: Gold
would save $0.80/day and cost $6,087 of fee to reach); the loss tail scales linearly and the ruin
table above is unforgiving. **Do not lower.** Cutting the request forfeits the free rationing option
in §1.3 and the cheap-tail convexity, for a saving the data cannot see.

### 1.5 Anything Kelly-shaped is refuted twice over

The brief's tape-capped Kelly result (−$14 to −$24 vs flat +$218) is not an accident of that
implementation. Two structural reasons it must fail here:

1. **Kelly sizes on estimated edge, and estimated edge is largest exactly where it is least real.**
   The `seen_ask` 0.55-0.75 lane reads **+17.2% ROI (n=79)** — by far the fleet's best. It is also
   the least robust thing in the book: LOO-day drops it from +$116 to +$60, eth and doge are
   negative, and its fills are dominated by dislocation sweeps whose own t is **+0.17** (§2.3).
2. **This is a fixed-bet book, not a fractional one.** Clips are denominated in dollars, not in a
   fraction of equity, so a drawdown does not shrink the next bet. Ruin is an absorbing state that
   Kelly's log-utility argument explicitly assumes away. The Kelly criterion is not merely
   unsupported here; its premise does not hold.

---

## 2 — Which coins: run all 7. Coin PnL ranking does not persist — it inverts.

### 2.1 The test that decides it

Split the 29 days in half (ERA1 08-17→08-30, 14d; ERA2 08-31→09-14, 15d) and rank coins by net:

| coin | ERA1 | ERA2 | sign stable? |
|---|---|---|---|
| bnb | −$27.9 | **+$197.0** | flip |
| btc | +$75.0 | +$59.6 | ✔ + |
| doge | −$2.4 | −$88.2 | ✔ − |
| eth | +$27.7 | −$10.4 | flip |
| hype | −$47.6 | **+$62.6** | flip |
| sol | −$31.8 | **+$89.0** | flip |
| xrp | −$1.9 | −$57.7 | ✔ − |

**Spearman rank correlation between halves = −0.500. Pearson = −0.267.** Sign-stable coins: 3 of 7,
against a permutation null of **3.88** — i.e. **P(≥3) = 0.92, worse than chance.**

The three coins that lost most in ERA1 (hype, sol, bnb) are the three that earned most in ERA2. Any
rule that had dropped coins on ERA1 PnL would have deleted ERA2's entire profit.

So: **doge −$86.75 and xrp −$32.29 over 29 days are not grounds to drop them.** doge is the best
candidate — it is negative in every single lane (cheap −42.5%, 0.75-0.90 −5.7%, mid −0.5%, 0.98
−1.6%, 0.99 −0.8%) and has the lowest fill rate at 0.98 (0.363 vs btc 0.918), which is the
signature of taker-side adverse selection. But at **−$2.69/day, 95% CI [−8.92, +1.44], P(>0) = 0.151**
it is not established, and §2.1 says coin-level PnL is the wrong evidence to use.

**7 coins is right**, and the reason is diversification of an already-tiny effective sample, not
per-coin edge. Dropping a coin forfeits its bars for a saving the data cannot measure.

### 2.2 The accidental de-selection is the real finding here

`eth` and `xrp` have not filled since **09-09**, `hype` since **09-10**. The fleet is being
de-selected by something that is not a decision — and it has removed three coins, two of which
(eth, hype) were positive in ERA2's first half. **Unmanaged selection is worse than either keeping
or dropping a coin, because it cannot be reasoned about or reverted.** This should be diagnosed
before any deliberate coin change is even discussed. I could not determine the cause read-only;
it belongs to whoever owns the pod layer.

### 2.3 Where the concentration actually lives

The brief's "top-1 fill = 31% of net" localises cleanly. Defining a **sweep** as a fill landing
≥5c below its displayed ask:

| | n | stake | net | $/day | t | days+ |
|---|---|---|---|---|---|---|
| all fills | 4,434 | $51,939 | +$242.79 | +8.37 | +1.25 | 19/29 |
| **non-sweep** | 4,342 | $50,735 | **+$213.14** | +7.35 | **+1.52** | 21/29 |
| sweeps only | 92 | $1,204 | +$29.66 | +1.02 | **+0.17** | 14/29 |

Sweeps are **2.07% of fills, 12.2% of net, and 28% of the variance**. They are a coin flip: 33
losses in 92 at a mean fill of 0.683, against a break-even loss rate of ~31.7% — *worse* than
break-even in expectation. Their +$29.66 is one bnb fill (+$74.82, 99.8 shares at 23.8c on a $23.76
request). Per coin the sweep lane is bnb +$107, sol +$19, btc +$18, **xrp −$12, doge −$17, eth −$37,
hype −$48**.

I tested the hypothesis that clip size is worth keeping *because* it buys convex exposure to these
sweeps. **It failed**: the sweep lane has no edge, and the deployed `PM_TE_TOXIC_BRAKE = 0.05` (stop
laddering a bar after a clip fills ≥5% below the ask) is already the correct response — it just does
not protect the *opening* clip.

---

## 3 — The lane finding that reversed, and why I am not proposing it

This is the most important methodological note in this document.

The mid-band (`seen_ask` ∈ [0.90, 0.975)) looked like the clearest allocation action in the book:
**−$156.51 over 29 days, $/day −5.40, 95% CI [−10.84, −0.65], P(>0) = 0.013** — the only lane in the
fleet with a significantly signed daily series. It is **gross-negative before fee** (−$128.06), so it
is a selection failure, not a cost failure: at 0.90-0.975 the implied loss rate is 2.5-10% and we run
6.5%. 6 of 7 coins negative, survives dropping the worst day *and* the worst coin (−$33.27). It
independently reproduced a pre-existing finding (§58, 08-30: "−$121.75/era, 6/7 coins negative, eth
the exception") — and that gate, `PM_TE_FIRST_SKIP_LO/HI`, is **not set in any values file**, so it
was never deployed.

Then I split it by era:

| | days | MID stake | MID net |
|---|---|---|---|
| 08-17→08-30 (overlaps §58's derivation) | 14 | $7,511 ($536/day) | **−$187.94** |
| 08-31→09-14 (out of sample) | 15 | $1,200 ($80/day) | **+$31.43** |

Out of sample the lane is **positive**, and excluding eth it is +$12.97, $/day +0.87, 95% CI
[+0.24, +1.73]. More to the point, **the fleet's exposure to the lane collapsed 6.7×** — something
between the vol-delay gate (§37), the slope gate, and the toxic brake already stopped it entering.

**Killing a lane the fleet has already stopped using buys ~$0.** My earlier policy ladder (worth
+$4.31 to +$9.81/day, all with P(>0) ≥ 0.99) is an artefact of an era that has ended. I am reporting
it because the reversal is the finding — this is bug #24's era trap, and the 29-day aggregate hides
it completely.

Every lane except the near-zero-ROI 0.99 lane flips sign between the two halves:

| lane (seen_ask) | ERA1 $/day | ERA2 $/day | ERA2 stake/day |
|---|---|---|---|
| cheap <0.75 | +1.89 | +5.54 | $23 |
| 0.75-0.90 | +4.75 | **−1.26** | $98 |
| MID 0.90-0.975 | −13.42 | **+2.10** | $80 |
| 0.98 | −1.97 | **+8.14** | $769 |
| 0.99 | +8.12 | +2.27 | $855 |

Clips 2+ flip too: **−$17.32 across 29 days, but +$61.61 in ERA2 alone.** The brief's "clip 1 is the
whole book" is an ERA1 statement.

**Conclusion: there is no stable lane-level or coin-level allocation to fit. Anything fitted to the
29-day aggregate is fitting a regime that has already changed.**

---

## 4 — Halts: inert as configured, and one real defect

### 4.1 They almost never fire

Replaying the deployed rule (`day_pnl − halt_base ≤ −LIMIT`, 1h cooldown) against the bot's own
`live_day_pnl` in the settle stream:

| coin | limit | episodes / 29d | days w/ trip | trips followed by orders inside the cooldown |
|---|---|---|---|---|
| btc | $30 | **0** | 0 | — |
| bnb | $30 | **0** | 0 | — |
| sol | $999 | 0 | 0 | — |
| xrp | $999 | 0 | 0 | — |
| eth | $30 | 2 | 2 | 0 ✔ |
| hype | $30 | 2 | 2 | 0 ✔ |
| **doge** | **$7** | **8** | 6 | **4** ✘ (−$22.86 in those windows) |

### 4.2 Defect 1 — the limit is smaller than one bar's exposure

`lives_per_episode` = limit ÷ p99 single-bar stake:

| coin | limit | p99 one-bar stake | max one-bar stake | worst bar | lives |
|---|---|---|---|---|---|
| btc/eth/bnb/hype | $30 | $47.5 | $47.5-57.5 | −$58.23 (hype) | **0.63** |
| doge | $7 | $39.5 | $47.5 | −$28.49 | **0.18** |
| sol/xrp | $999 | $47.5 | $49.8 | −$47.55 (xrp) | 21.0 |

A single bar can stake **$47.52 — 1.6× the entire daily limit**. The halt therefore cannot prevent
the loss it is sized against; it is a post-hoc day-stop that fires *after* the damage, not a risk
control. The config comment "halt $30 = same 2-losses-and-out policy per dollar" is **arithmetically
wrong at the current clip**: it is ~0.6 losses and out, i.e. the first loss of any size trips it.

And the limits are **inverted relative to the tails**: sol (−$46.46 worst day) and xrp (−$42.94) are
the two coins with *no* limit, while btc (−$20.25) and bnb (−$18.36) — which never came close — carry
$30.

### 4.3 Defect 2 — the halt state does not survive a restart

`PM_TE_RISK_PERSIST` defaults to `"0"` (`twapedge.py:160`) and **`pmTeRiskPersist` appears in no
values file** — only in `chart/templates/secret.yaml` with a `default "0"`. So `live_day_pnl`,
`halt_base` and `halt_until` are wiped on every pod restart. This is the measured cause of doge's 4
post-trip order leaks: the coin resumed inside its own cooldown with a zeroed day counter.

This is also the §"acknowledged-risk-is-the-deploy-plan" failure mode in miniature — a risk control
that silently does not exist is worse than no control, because it is budgeted against.

### 4.4 What a coherent halt would look like (not a deploy proposal)

Set the limit as a **multiple of one bar's maximum exposure** — the only unit that is scale-invariant
and therefore survives any future sizing change automatically:

`LIVE_MAX_DAILY_LOSS_USD = 3 × (LIVE_MAX_ORDER_USD + WHALE_LADDER_USD)` ⇒ **~$143** at current sizes,
**~$27** for doge.

At $143 the rule would have fired **0-1 times in 29 days across the fleet** — the right frequency for
a catastrophe stop, versus today's 12 episodes that mostly punish doge for a single ordinary loss.
Benching a coin forfeits its subsequent bars, and §2.1 says we have no basis for believing a losing
morning predicts a losing afternoon; so the halt should be sized to stop a *catastrophe*, not a
*drawdown*.

---

## 5 — Drawdown and ruin at the proposed (= current) size

Day-block bootstrap, 20-40k paths, 365 days, resampling the 29 observed daily nets. **Never Gaussian**
— the input is the empirical daily distribution (min −$74.56, max +$123.19, sd $35.93).

| scenario | median terminal | 5th pct | median max DD | p95 max DD | P(<$150) | P(<$50) |
|---|---|---|---|---|---|---|
| as measured, $8.37/day | $3,508 | $2,402 | **$250 (56% of E0)** | $419 (93%) | 1.0% | 0.2% |
| half the edge, $4.19/day | $1,976 | $869 | $374 (83%) | $687 | 10.6% | 5.2% |
| **edge = 0 (not rejected at t=1.25)** | $445 | −$652 | **$727 (162%)** | $1,449 | **63%** | **53%** |
| edge = 0, clip ×1.5 | $447 | −$1,201 | $1,088 | $2,179 | 75% | 67% |
| edge = 0, clip ×2 | $437 | −$1,766 | $1,460 | $2,918 | 80% | 75% |

Read the drawdown row honestly: **even if the edge is exactly as measured, the median one-year path
draws down 56% of the starting bankroll and 1 in 20 draws down essentially all of it.** Ruin stays
low only because the book grows faster than the drawdown scale — a fixed-bet property that
disappears the moment the edge does.

Detection horizons against sd $35.93: **$8.37/day needs ~144 days**, $4/day ~633 days, $2/day
~2,530 days. Every sizing question in the brief moves $/day by less than $4. **They are undetectable
and must be decided on mechanism or not at all** — which is what §1 and §2 do.

---

## 6 — Reallocation vs new risk

These are separate propositions and only one of them is live:

* **Reallocation** (move budget from a zero-EV use to a positive-EV one) — I found **no stable
  zero-EV pocket to harvest**. The two candidates both dissolved: the 0.99 lane looks like a $22k
  capital sink returning +$0.14 when cut by *fill* price, but at the *attempt* level (the only
  fill-model-free unit) it nets **+$147.74 / +$5.09 per day**, because a 0.99 displayed ask is where
  the dollar-denominated FAK catches its cheap fills. The mid-band reversed out of sample (§3).
* **New risk** (add exposure) — this is the only proposal actually on the table anywhere, and §5
  prices it: at k=1.5-2 the zero-edge branch gives P(ruin) 50-60% over the information window, and
  the venue lane has closed the two arguments that could have justified it (no volume-tier unlock,
  no liquidity rewards, no rebate accrual). **Reject.**

There is genuine *bankroll* headroom (peak exposure 32% of equity). There is no *evidence* headroom.
Those are not the same thing, and only the second one licenses a size increase.

---

## 7 — What would reverse each call

| call | what reverses it |
|---|---|
| **hold clip size** | A within-stratum $/fill difference between request sizes whose day-block CI excludes zero — needs ~150+ days at the current gap, or a deliberate randomised size arm (alternate $8/$24 per bar by hash of bar id) which would settle it in ~40 days because it removes the between-condition variance. **That arm is the single highest-value experiment I can name.** |
| **hold 7 coins** | Split-half Spearman on coin PnL turning *positive* over a longer window, or a coin showing a mechanism-level (not PnL-level) defect — e.g. doge's 0.363 fill rate at 0.98 being shown to be adverse selection rather than depth. |
| **do not size up** | The fleet clearing t ≈ 2 on its own record (≈144 days at the current $/day), *and* a depth study showing the 0.98 lane has unfilled bar supply. Both, not either. |
| **halt re-parameterisation** | Evidence that a losing morning predicts a losing afternoon within a coin-day — i.e. that the daily-loss stop has any forecasting content. I did not test this and it is testable; if intraday loss autocorrelation is real, a *tighter* halt beats a looser one and §4.4 inverts. |
| **the whole book** | 60 more days at t < 1.5 should close it. The book returns 1.86%/day on $450 if real — an implausible number that should not be defended indefinitely on a t of 1.25. |

---

## 8 — The only change I would put forward

**Not a deploy proposal.** Named here so the user can decide.

**Proposal H1 — make the halt layer real rather than nominal.**
1. Set `pmTeRiskPersist: "1"` on all 7 coins so `live_day_pnl` / `halt_base` / `halt_until` survive
   restarts.
2. Re-express `liveMaxDailyLossUsd` as `3 × (liveMaxOrderUsd + pmTeWhaleLadderUsd)` — $143 for the
   six $24-tier coins, $27 for doge — replacing the current 7 / 30 / 999 spread.

* **Revert path:** unset `pmTeRiskPersist` (reverts to the `default "0"` in `templates/secret.yaml`)
  and restore the literal per-coin `liveMaxDailyLossUsd` values recorded in §4.1. Single-key helm
  revert per coin, no code change, no behavioural coupling to the trading path.
* **Judging metric — explicitly NOT PnL:** (a) **post-halt order leakage** — count of
  `PF_TE_WHALE_ORDER` events landing inside a cooldown window; target **0**, currently 4 of 12
  episodes. (b) **halt episodes per coin-week**; target ≤ 1 fleet-wide, currently ~3. Both are
  countable within 7 days and neither depends on the edge being real.
* **Behavioural warning:** this *loosens* the effective stop on doge (7 → 27) and *tightens* it on
  sol/xrp (999 → 143). It will change which bars the fleet sees. It is a behavioural change, not a
  neutral one — and per the standing rule, an unknown must mean delay, not "acceptable".
* **Caveat I cannot resolve read-only:** `PF_TE_LIVE_HALT` events were not in the pulled ledger, so
  §4.1 is a *replay* of the halt rule against the bot's own `live_day_pnl`, not a direct observation
  of halts firing. Pulling that event type would confirm or break §4.2-4.3 in one command.

**And one diagnosis, ahead of any allocation change: find out why eth/xrp stopped firing on 09-09 and
hype on 09-10 (§2.2).** Three of seven coins have left the book by accident. No sizing or
coin-selection decision should be made on top of an unexplained de-selection.
