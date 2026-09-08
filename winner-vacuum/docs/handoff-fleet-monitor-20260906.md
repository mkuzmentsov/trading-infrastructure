# FLEET-MONITOR HANDOFF — 2026-09-06 (mrec v2 trade-tape pass, notes §66)

**For the session babysitting the live vacmaker fleet.** Everything here comes from
`docs/vacmaker-offline-notes.md` §66; this file is only the operational slice —
what to watch, what to expect, what not to re-derive, and what to do if the user
greenlights the one open candidate. Playbook itself is unchanged (see the
`live-bot-babysitting` memory).

---

## 0. NOTHING WAS DEPLOYED. Fleet config is byte-identical to before this session.

The user said "no code for now". No env var, no image, no pod was touched. If you
see a behaviour change on the fleet, it did **not** come from here — investigate it
as a real incident. Current gates remain exactly as §61/§59/§58 left them:
tl∈[3,20] via the vol-delay gate, threshold `0.10 + 0.035·max(0, tl−14)`, cov≥0.5,
ask 0.55–0.99, first-clip skip 0.90–0.98 (eth exempt), ladder floor 0.94,
$8 clips / $16 bar, 8s re-entry gap, 1h halt episodes, xrp toxic-brake + risk-persist.

---

## 1. ⭐ THE ONE LIVE-CHECKABLE EXPECTATION: the loss signature

This is the highest-value thing to carry into monitoring. On the 09-01→09-06 replay,
**a losing clip almost always shows the favourite's own BID collapsing just before we fire:**

| | share with bid drop ≤ −3¢ in the prior 20s |
|---|---|
| losing clips (n=42) | **69.0%** |
| winning clips (n=680) | 13.4% |

and **69.2% of all loss dollars** sit in that bucket. Every single losing clip had
`|est| < 5bps` (0 losses at |est|≥5bps).

**What to do with it:** when a bar loses, don't just log it — classify it.
- *Bid-drop loss* (the favourite's best bid fell ≥3¢ in the ~20s before the fire):
  **expected**, already understood, no investigation needed. Add it to the tally and move on.
- *Non-bid-drop loss at |est| ≥ 5bps*: **this should not happen.** 0 occurrences in 6 days
  of replay. If you see one, it is a real anomaly — suspect a stale/rolled market, a
  wrong-window fire, or a settle-pipeline defect, and escalate.

**Cheap proxy if you can't compute the bid history live:** bid-drop clips slip ≥5% off
their displayed ask **29.2%** of the time vs **5.1%** for the rest. So a
`PF_TE_TOXIC_BRAKE` event (xrp's §59 5%-slippage brake) is ~6× more likely on exactly
this class. Where the brake is live, its firing rate is a usable proxy for how much
bid-drop flow the coin is eating.

---

## 2. IF the user greenlights the bid-drop veto — volumes, staging, and what you will actually see

Rule: **skip the clip when `|est| < 5bps` AND `(favourite best bid now − same side's best bid 20s ago) ≤ −0.03`.**
Needs only a ~20s ring buffer of the favourite side's best bid — no oracle, no trade tape.
The `|est| ≥ 5bps` exemption is load-bearing: there the arithmetic is settled and a falling
bid is a *gift* (+3.2% ROI on that subset).

### 2a. How much trading it touches (replay, 09-01→09-06, 7 coins)

Fleet baseline **120 clips/day** over **106 bars/day**, $963 staked/day.
With the veto: **107 clips/day (−11%)**.

⚠️ **Corrected 2026-09-06 (§67) — quote the risk metrics, NOT a $/day delta.** The
"$12.66→$29.49/day" figure in the first draft was one cell of a 12-cell fill-model grid.
Across the whole grid the *baseline* spans −$8.3…+$35.4/day while the *veto* spans
$13.7…$30.1/day, so the delta ranges −$5.3 to +$26.7 and is not established offline.
What holds in **every** cell:

| | baseline | with veto |
|---|---|---|
| losing clips / day | 4.7 – 7.3 | **1.5 – 2.3** |
| worst DAY | −$34 … −$76 | **+$1.6 … +$6.6** |
| worst single BAR | −$16.3 … −$16.7 | **unchanged** |

So it is a **day-level tail filter**: it does not stop the single worst bar, it stops bad
bars accumulating within a day. Judge it on loss count and worst day. Never report a
PnL delta from a replay.

It blocks **19.5 fires/day fleet-wide** — of which **4.8 would have lost and 14.7 would have won.**
That ratio is the whole design: payoff is ~30:1, so blocking 3 winners to stop 1 loser is correct
(§37 — win count is useless on this fleet). Per coin per day:

| coin | clips/d | blocked/d | of those, lose/d | of those, win/d | replay $ saved/d *(one fill model — direction only)* |
|---|---|---|---|---|---|
| eth | 22.8 | 2.5 | 1.0 | 1.5 | **+4.42** |
| bnb | 14.8 | 3.7 | 1.2 | 2.5 | **+3.55** |
| xrp | 20.5 | 4.5 | 1.2 | 3.3 | **+2.88** |
| doge | 15.0 | 2.0 | 0.3 | 1.7 | +1.98 |
| btc | 15.2 | 1.0 | 0.3 | 0.7 | +1.11 |
| hype | 11.7 | 2.5 | 0.3 | 2.2 | **−1.83** |
| sol | 20.3 | 3.3 | 0.5 | 2.8 | **−2.45** |

### 2b. ⭐ Stage it — a blocking single-coin A/B is UNDERPOWERED, do not start there

Per-clip PnL sd is $2.4-3.2 and the per-coin effect is only $3-4/day, so on eth a blocking A/B
reaches **t=1 at ~7 days and t=2 at ~26 days**; bnb ~49 days, xrp ~76 days. A one-week
single-coin pilot **cannot** answer this. Two better steps first:

1. **Zero-code option (preferred first move).** The mrec recorders already log everything the rule
   needs (SNAP bid ladders + `cl` + RES). Just **re-run the replay in 2-3 weeks** on 3× the data —
   `winner-vacuum/tools/mrec/`, no fleet change, no risk. Keep the recorders alive; that is the
   only operational requirement.
2. **Log-only arm, fleet-wide (if we want live truth sooner).** Emit `PF_TE_BIDDROP` on every fire
   the rule *would* have blocked, carrying ask / est / dB — but still take it. Zero behaviour
   change, and it yields **19.5 scored events/day fleet-wide** (~136/week) with real fills instead
   of ~2.5/day on one blocking coin. This is exactly the `PF_TE_WHALE_DELAY` pattern that refuted
   §64, and it is the reason to trust the answer.
   **Expect the tagged fires to lose ~25% of the time vs ~4% baseline.** If they don't, the rule dies.
3. **Only then** turn on blocking, one coin, **eth or bnb** (largest positive, mid-band-prone).
   **Never hype or sol** — both are negative in replay. Deploy at a UTC-00:00 rollover if the pilot
   coin is near a halt, so the restart doesn't un-halt it (§26 MUST-DO).

### 2c. What to expect after redeployment — and what NOT to conclude

- **Visible within days:** losing clips drop from ~7/day to ~2/day fleet-wide (or ~1.3→~0.3 on a
  single pilot coin). Loss *count* and worst-bar are the metrics that move fast.
- **Not visible within a week — and not well defined offline:** the PnL delta. Across fill
  models it ranges −$5.3 to +$26.7/day (§67-1). Report live PnL as "consistent with / not yet
  separable from" the replay, never as confirmation, and never quote a replay delta as a target.
- **You WILL see it block winners** — by design, 3 winners per loser. Expect exactly one
  "it blocked a good bar" observation per coin per day. Do not treat that as a defect and do not
  loosen the threshold in response; on 09-05 the veto forfeits ~$55 while turning 09-02 from
  −$58.70 into +$36.12. It is a tail filter.
- **Clip count falls ~11%.** If it falls much more than that, the ring buffer or the est exemption
  is wrong — check that `|est| ≥ 5bps` fires are still going through.
- **Do not tune it live.** Threshold −0.01…−0.15 and lookback 5/10/20s all give $26-33/day in
  replay. Insensitivity is the evidence it is real; tuning would only fit noise.
- **It will forfeit real windfalls.** On a bid-drop bar the FAK genuinely does fill cheaper
  (the §65-3 bnb-0.238 class), and bid-drop clips are *more* fillable than the rest (53% vs 47%).
  In the two fill-model cells that assume a deep sweep on a narrow window, the veto is
  net-negative. This is the one honest argument against it — watch for it in the log-only arm.
- **Do not extend it to tl > 20.** Tested and refuted (§67-2): in the early lane the sign
  *inverts* (no-bid-drop −$27.8/day, bid-drop +$7.2/day). It is a late-window tool only.
- Sizing up is the natural follow-on, but **not before** this proves out: §65-2 refuted the cap
  raise on live fills (82 bars at ≥$44 spent, pooled −$54.40).

## 3. Questions you can now answer without re-running anything

Someone will ask these during monitoring. The numbers are settled; don't re-derive.

- **"Should we raise the clip/ladder size?"** Supply is not the constraint — median top-of-book
  on a fireable bar is **$29** (p75 $68) vs our $8 clip / $16 bar cap. But §65-2 refuted the cap
  raise on live fills (82 bars at ≥$44 spent, pooled −$54.40). The cap is saving money.
  The bid-drop veto is the change that would make sizing up safe — in that order, not before.
- **"Why do we miss so many bars?"** The favourite has **no ask at all in 83% of late-window
  seconds.** Venue truth, not a recorder artifact (REST agrees with our WS on ask *presence*
  in 99.9% of 66,764 reconciles). Missing bars are usually missing supply, not a bot fault.
- **"Can we rest a bid instead of taking?"** No. The pool is real ($105k/day of correctly-sided
  taker sell flow at 0.95–0.99) but the bid queue at the hit price is **median 17,391 shares**
  (p25 4,254). A $12 clip is 0.07% of the queue. Re-closed 09-06 with the queue measured.
- **"We're only making $19/day, where's the rest?"** Late-window takers as a class extract
  ~$3.2k/day from makers. We hold ~$100-150 of capital. The gap is capital and per-bar
  deployment, not signal — same conclusion as §32.
- **"Should we fire earlier, at tl 25-35, on those cheap asks?"** No — §64 closed it and §67-2
  re-closed it with the bid-drop split (the sign inverts there). Calibrated: 22 fires/day,
  74.2% win, −$20.7/day at $24 clips, matching the live A/B. Note the trap that nearly reversed
  this (bug #26): a replay that scans below the bot's real `MIN_ASK=0.55` reads **+$270/day**
  of profit that does not exist.
- **"What about the 1h / 15m markets?"** 15m and 1h are dead (−0.6%/−1.2% and −7.1%).
  ⚠️ And **1h TWAP-60 recon is only 95.2% accurate** vs 99.7% on 5m/15m — the 1h market is
  probably not TWAP-60 at all. Never run a recon strategy on 1h until its window is identified.

---

## 4. Standing items with dates

| when | what |
|---|---|
| **~2026-09-27 → 10-04** | Re-cut the **4h lane** (§66-4). Today: 24/24 wins, +5.94% ROI, books ~1.7× deeper than 5m (median top-of-book $49 vs $29) — the one place our capital-per-bar cap would bind less. But n=24 / ~5 fires per day. Needs ~150 fires before anyone writes code. **Keep all five 4h recorders running** — if a 4h pod dies, that clock restarts. |
| next recorder redeploy | `price_change` rows carry no `ws` (95% of the event stream unattributable). One-line fix in `multi_recorder._emit_raw`: resolve the market from the first change's `asset_id`. Logged in `docs/backtesting.md`. Not urgent — SNAP covers current research. |
| ongoing | Never judge recorder health on the RB hash flag (btc 45.6% and that is *normal*). Use `evage` + file growth + RB presence. |

---

## 5. Where things live

- Full analysis and every number: `docs/vacmaker-offline-notes.md` **§66**
- Decision-map rows (bid-drop, resting-bid re-closed, 15m/1h dead, 4h flagged): `docs/README.md` §1
- Reproducible parquet pipeline: `winner-vacuum/tools/mrec/` (+ its README)
- Two rules baked into that pipeline, do not remove: relay-lag the Chainlink ticks (bug #25 —
  the replay in this file is *not* clairvoyant, measured lag p50 2.13s) and tape-confirm every
  fill (bug #23). Removing either reads roughly +$3k/6d of profit that does not exist.

---

# ADDENDUM — 2026-09-06 evening session (§68). Read this before acting on anything above.

**Still nothing deployed. Fleet config untouched.** What changed is the *measuring instrument*.

## A. The replay this handoff quotes was mis-specified in two ways (bug ledger #27)
1. It ran **$8 clips / $16 bar**. The fleet runs **$24 / $48**. Every $/day above is at ⅓ scale.
2. It let the fill price come from prints up to **1.5-3.0s** after the decision. Measured on the
   10Hz ladders, an ask ≥5¢ better than displayed appears within 0.2s on **1.3%** of fires and
   within 1.5s on **7.0%** — so most of that "price improvement" arrives after our order (0.4s
   scan + ~200ms venue latency) would already have landed.

**House fill model now: 0.4s window, ZERO price improvement, size walked down the displayed top-3
ask ladder, tape-confirmed, $24/$48.** Scored against the day closes for 09-02…09-04
(live **+$18.40, 351 bars, 17 loss bars**) it is the best of twelve cells on all three axes at once
(**+$34.94, 312 bars, 22 loss bars**) and still overstates PnL ~1.9×. The cell §66/§67 used carries
**34** loss bars — double the live count, i.e. it scored the veto against twice the loss population
the veto exists to remove.

## B. What that does to the veto's expected effect — revise §2a/§2c above
The veto survives, and the *shape* claims in §2c are unchanged and if anything firmer:

| | baseline | with veto |
|---|---|---|
| losing clips / day | 4.2 | **1.2** |
| worst DAY | −$63.36 | **+$6.82** |
| loss clips over 6d | 25 | **7** (better on 5 of the 6 days) |

⚠️ **but the dollar delta is positive on only 3 of 6 days, and leave-one-day-out shows it goes
NEGATIVE (−$8.85/day) if 09-02 is dropped.** The entire dollar benefit is one bad day. Threshold
(−0.01…−0.15), lookback (5/10/20s) and leave-one-COIN-out are all insensitive — the fragility is
day count, not parameters. So: **if a pilot runs, score it on loss-bar count, which moves on 5 days
out of 6. Do not score it on PnL, which moves on one.** Expect ~+$5…+$7/day at most, after
discounting the sim's 1.9× overstatement.

## C. Do NOT pick the pilot coin from the replay
Per coin, the calibrated cell is **anti-correlated** with the live fleet (r = −0.63 on 4-day coin
totals; live doge −$84.76 vs sim +$21.8, live sol +$67.81 vs sim −$30.7). With ~20 loss bars and a
30:1 payoff, a coin's PnL is decided by which individual bars flipped. §66's "pilot on bnb or eth"
and §68's own per-coin table are both replay artifacts. **Choose the pilot coin from live loss-bar
counts instead.**

## D. Questions this session closed — don't re-open them during monitoring
- **Fade the stale estimate instead of skipping?** ⛔ −58.7% ROI. On a bid-drop bar the pair sum
  `fav_ask + dog_ask` has a **median of 1.45** — the book is withdrawn, not mispriced, and since
  `ua ≡ 1 − db` a collapsing favourite bid makes the dog *dearer*. There is no side to take.
- **The 04-08 UTC hole / tl 16-20 cell / UP-DOWN asymmetry** (three open analytics leads): all
  three are the bid-drop share in disguise. Negative hours run 28-35% bid-drop share vs under 6%
  in the strong hours. **Do not add an hour or side gate** — it is a lossy proxy for dB.
- **§65-5 late-shift (fire only tl≤14)?** ⛔ Retains only 45-55% of stake; the ROI gain does not
  pay for it. Supply, not capital, is the constraint.
- **Raise MIN_ASK to 0.98** (flagged open 09-02)? ⛔ Dominated: $13.33/day vs the veto's $37.60,
  because it discards the profitable cheap band along with the bad one. Keep MIN_ASK=0.55.
- **Drop §58's first-clip skip now that dB exists?** ⛔ No — it is complementary; removing it costs
  $11.55/day even with the veto on.
- 🟡 **The one new candidate:** the ladder-cap raise *conditional on the veto* is monotone in
  dollars with flat loss count ($24/$48 → $72/$144 = $37.60 → $69.03/day). §65-2 only ever tested
  it unconditionally. **Not before the veto proves out live** — it leans on displayed top-3 depth
  being takeable, which bug #23 says it is not in the cheap band.

---

# ADDENDUM 2 — the candidate CHANGED. If a pilot happens, run vR, not vB (§70)

**Still nothing deployed.** A second fork mined the full 10-level ladders (dead — §71) and fell
out of it with a better form of the same rule.

## The rule
```
skip the clip when   (fav_bid_now − fav_bid_10s_ago) / fav_bid_10s_ago  <=  −0.20
```
vs §66's `dB20 <= −0.03 AND |est| < 5bps`. Same ~20s ring buffer of the favourite side's best bid
that §66 already required, plus one division. **No `|est|` carve-out is needed** — the relative
rule fires zero times at |est| ≥ 5bps on this sample, so the exemption is a no-op.

Why relative: a 3¢ fall is noise at a bid of 0.99 and a collapse at a bid of 0.40. The absolute
rule over-vetoes the top of the book and under-vetoes the middle. Concretely, of the clips the two
rules disagree on: **vB-only = 60 clips at 90% win / +10.5% ROI** (profit vB discards and vR
keeps), while the overlap vB∧vR = 57 clips at 59.6% win / −23.8% ROI is the genuinely toxic core.
Marginal vR inside the vB-kept set: **p=0.0095** (it adds). Marginal vB inside the vR-kept set:
**p=0.988** (it adds nothing).

## What you should expect to see, in the calibrated cell ($24/$48, 0.4s, 0¢ improvement)

| | $/day | losing clips/day | worst day | chop days | calm days |
|---|---|---|---|---|---|
| baseline | 27.41 | 4.2 | −$63.36 | −$11.09/day | +$59.94/day |
| vB (§66) | 37.60 | 1.2 | +$6.82 | +$48.20/day | **+$40.80/day (−$19 vs base)** |
| **vR** | **44.89** | 1.7 | +$6.82 | +$30.84/day | **+$66.94/day (+$21 vs base)** |
| vR at −0.15 | 51.73 | 1.2 | +$4.95 | +$61.22/day | +$60.99/day |

**⭐ The operationally important row is the last two columns.** §69 established that the sample
contains a chop regime (09-02, 09-03) and a calm regime (09-04 onward). **vB is insurance: it pays
in chop and costs ~$19/day in calm. vR is positive in both.** That is the difference that should
decide which rule gets piloted, because a pilot week is more likely to be calm than choppy — and a
calm week would make vB look like a failure when it is working as designed.

## Staging — unchanged from §66-2b, with one added instruction
1. **Log-only arm first**, fleet-wide, emitting the rule's decision without acting on it. Now emit
   **both** `rB10` and `dB20` so the two rules can be compared on live fills. ~19 scored events/day.
2. Then blocking on one coin. **Do not choose that coin from the replay** — per-coin replay results
   are anti-correlated with live (r = −0.63, §68-3b). Choose it from live loss-bar counts.
3. Judge on **loss-bar count**, which improves in both regimes. For vR you may *additionally*
   expect a PnL gain in a calm week; for vB you should not.
4. Sizing stays where it is. §68-8's conditional cap raise is further undercut by §71-3: median
   takeable notional on the "gift" fires is **$17.70** and only 38% carry ≥$32.

## Health metric worth logging regardless of any of this (§69)
Per coin per day: **the share of fire-window bars where the favourite is offered at all**, and the
**p25 of the minimum ask reached**. Those moved 26-28% → 14-17% and 0.52 → 0.73-0.80 between 09-03
and 09-04. If that persists, the addressable pool has roughly halved and it matters more than any
veto. Free to compute from state the bot already has.

---

# ADDENDUM 3 — ⛔ READ THIS ONE. It retracts Addendum 1's supply claim and re-ranks the candidates.

An adversarial pass (notes §72), independently re-verified, overturned part of the two addenda
above. **Still nothing deployed.** Corrections, in order of how badly they mislead:

## 1. ⛔ RETRACTED: "the addressable pool halved after 09-03" (Addendum 2's health metric)
It did not. What vanished was a layer of **ghost quotes**. On bars settling |margin| ≥ 5bps, the
recorder showed 4,739 seconds of cheap favourite-side asks across 271 bars at a median 0.51 —
against which a matching print exists on **1 bar**. After 09-03 that layer stopped being quoted
and the *print rate* of cheap favourite offers **rose from 0.24 to 0.75**. Supply did not fall;
the fake part of it cleared. **Do not log or act on the Addendum-2 "health metric" as written** —
any availability statistic must require a matching print (bug #23 addendum).

## 2. ⚠️ Every $/day figure in Addenda 1 and 2 is inflated ~2× (bug #28)
The replay let one qualifying print authorise the whole displayed top-3 ladder. Capping each clip
at the shares that actually printed:

| | as reported above | corrected (tape-size capped) |
|---|---|---|
| baseline | $27.41/day, worst day −$63.36 | **$14.00/day, worst day −$1.59** |
| vB | $37.60/day | $23.90/day |
| vR | $44.89/day | $28.09/day |
| **losing clips/day (base / vB / vR)** | **4.2 / 1.2 / 1.7** | **4.2 / 1.2 / 1.7 — unchanged** |

The corrected baseline is 1.17× live over 09-02…09-05 (vs 2.60× before). **The worst-day story
collapses in both directions** — the uncapped model overstates the tail 3× vs live's −$20.45 on
09-02, the capped one understates it 13×. **The veto's tail benefit is not measurable offline.**

## 3. ⚠️ vR does NOT clearly beat vB. Log both; do not pre-rank them.
vR wins on dollars in 12/12 fill cells. **vB wins on losing-clip count in 12/12** (1.2 vs 1.7/day).
Loss count is the fill-model-independent metric this program agreed to trust; dollars is not.
vR's p-value is **0.01–0.08** once the null is stratified on spread (its vetoed set has median
spread 0.45 vs 0.04 kept) and corrected for the 33 rules scanned — not p<0.0001. And 33% of vR's
sim gain is "replacement clips" that only exist because the sim re-ladders after a veto.
**Emit both `rB10` and `dB20` in the log-only arm and let live fills rank them.**

## 4. ⭐ NEW, SIMPLER COMPETITOR: MIN_ASK 0.90
Under the honest size model: MIN_ASK 0.55 = $14.00/day at **4.2** losses/day; **MIN_ASK 0.90 =
$14.62/day at 0.7** losses/day; 0.98 = $10.39/day at 0.5. Raising the floor to 0.90 removes **83%
of the losses at no cost in dollars** — and it is one env var, no ring buffer, no new state.
Addendum 1's "MIN_ASK 0.98 is dominated, keep 0.55" was a house-cell artifact. **This should be on
the table alongside the veto, and it is much cheaper to try.**

## 5. ⭐ The counter-example to watch for on the fleet
Live 09-06 03:15 UTC bnb — the era's biggest single-bar win, **+$76.09**, was a **99.8-share fill
at $0.238 against a displayed ask of 0.62**. `rB10 = −0.966`, `dB20 = −0.94`: **both vetoes would
have blocked it.** Clips are dollar-capped, so price improvement buys shares super-linearly and
one such bar is worth ~5 days of fleet PnL. Blocking the class is right on average (deep late
prints run 128 winner-side vs 471 loser-side, −$1,046/day taken blindly) — but vB deletes the good
half preferentially (70.3% of winner-side deep prints sit in a vB-state vs 39.1% of loser-side).
**In the log-only arm, count these explicitly: bars where the FAK fills ≥20% below the displayed
ask, and their PnL. Only the fleet can produce that number, and it is the real risk of the veto.**

## 6. What is actually established, for a deploy conversation
- **The loss-clip reduction, 4.2/day → 1.2 (vB) / 1.7 (vR), is identical under every fill model.**
  That is the only claim to put in front of a decision.
- Sizing is closed (again — §65-2 was right; the monotone cap raise was the bug).
- The exit lane is closed permanently (`ub ≡ 1−da`; exiting at bid q ≡ buying the dog at 1−q).
- Everything still rests on **25 losing clips over 6 days, with 09-02 dominating**. The cheapest
  real progress is still to **wait 3-4 weeks and re-cut** — now with the tape-size cap in the
  harness and every availability statistic tape-gated.
