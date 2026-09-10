# Entry timing & clip-budget placement — where should the fire window sit? (2026-09-10/11)

**Agent B, 5m edge hunt.** Question: the §33 proposal to shift the clip budget later
(`tl<=20` → `tl<=12/14`) has never been tested properly. Test it, and rebuild the
accuracy-vs-time-left curve on the fresh 9-day tape.

## VERDICT: ⛔ REFUTED — do not tighten the late-fire delay. Keep `PM_TE_WHALE_VOL_DELAY_TL=20`.

The change that was on the table (`pmTeWhaleVolDelayTl: "20"` → `"14"`, or `"12"`) is
**not supported by either instrument**. Two independent, non-overlapping mechanisms kill it:

1. **Accuracy does not improve on the population you can actually trade.** Unconditional
   accuracy rises steeply as `tl` falls — but *conditional on a takeable ask existing* it is
   **flat at 95.4-97.1% across every tl band**. A cheap ask exists precisely when the market
   disagrees with us, and that is when our estimate is most likely wrong. Waiting buys accuracy
   only on bars nobody will sell you.
2. **The budget the proposal wanted to redeploy does not exist.** Live bars spend **$19.2 of
   the $48 ladder**; 1.04 clips/bar; only **1.9%** of bars reach the cap. §33's stated mechanism
   ("`WHALE_LADDER_USD=16` is exhausted early, leaving no budget for the late lane") was true at
   $16 and is **false at $48**. Nothing is being crowded out.

And the availability premise is off by ~4×: **§65's "68.8% ask persistence tl18→tl13" counted
DISPLAYED asks. Tape-confirmed it is 18.0%.** (bug #23 again, this time inside a persistence
statistic.)

---

## 1. Method and fill cell

* Tape: `every-tick-single/data/mrec/`, **09-01 20:00 → 09-10 20:00 UTC**, 7 coins.
  Shared parquet `every-tick-single/data/pq` (not rebuilt).
* **New derived panel** (mine, in scratchpad, not the shared dir): `panel04.parquet` — the
  panel rebuilt at the **0.4s cadence of the live `whale_loop`** (`WHALE_SCAN_S=0.4`), 1.41M
  rows. The shared 1Hz panel under-samples the scan by 2.5× and produced only half the live bar
  count; at 0.4s the replay's bar count matches live. Relay-lag gate is byte-identical to
  `panel.py` — the TWAP window ends at `min(end-3, cl_ts+1)`, the SNAP row's own `cl_ts`
  (**bug #25**). Confirmed live: `twapedge._estimate` → `rtds_state.window_mean` returns the mean
  over *received* ticks only, exactly what the panel computes.
* Gates replicated from `chart/bots/*_vacmaker.yaml`: `THRESH=0.5` bps (⚠️ `polysim2.py`'s
  default `0.10` is **not** the live value), `SLOPE=0.035`, `ANCHOR=14`, `cov>=0.5`,
  ask ∈ [0.55, 0.99] (`WHALE_CAP`, not `pmTeMaxAsk`), first-clip skip 0.90-0.98, ladder floor
  0.94, 8s cooldown, `$24` clip / `$48` ladder, FAK limit = `min(ask+0.01, 0.99)`.
* **Fill cell (bug #27 house cell)**: window **0.4s**, tape-confirmed BUY print at ≤ limit,
  size walked down the **displayed top-3 ask ladder** at prices ≤ limit.
  * *(a) strict* — price improvement **0¢** (fill AT the displayed ask).
  * *(b) sweep-permitting* — the FAK takes the best qualifying print inside the same **0.4s**
    window. This is not the 1.5s clairvoyant variant; 0.4s ≈ the real order flight, and the
    stale-ask sweep is documented as ~40% of btc profit.
  **Every verdict below holds in both cells.**

### Scoring against ground truth (rule 3)

I also pulled the **live event ledger** read-only from all 7 pods
(`PF_TE_WHALE_ORDER` / `PF_TE_WHALE_DELAY`, 09-01→09-10, 1,761 fires / 1,002 fills) and joined it
to `res.parquet`. This is venue truth for the whale lane, net of fees:

| | bars/day | loss bars/day | net $/day | fee $/day |
|---|---|---|---|---|
| **LIVE whale lane** (event ledger, 10d) | 96.4 | 3.00 | **+$15.61** | $4.07 |
| replay, sweep-permitting cell, `tl<=20` | 117.2 | 4.88 | +$20.07 | $7.82 |
| replay, strict 0¢ cell, `tl<=20` | 117.2 | 4.88 | +$4.56 | $7.17 |

The sweep-permitting cell is within ~25% on all three axes and is the primary instrument; the
strict 0¢ cell reproduces bars and loss bars but only 29% of the PnL, because it structurally
forbids the sweep. Treat absolute $/day as unreliable (the published `+$34.94/312/22` benchmark
cannot be rebuilt — `calib.py` is missing from the repo); **the trustworthy form is the paired
relative A/B under one fill model**, reported with loss-bars/day.

⚠️ **Two reconciliations worth recording.**
* RESEARCH-LOG day closes are **gross of the taker fee** (~$5/day fleet-wide). The whale-lane
  net above (+$15.61/day) is the number to compare a net replay against, not the ~$19.9/day headline.
* The live *fill* ledger (data-api /activity) tops out at **tl 18.0s**; our own event log tops out
  at **decision tl 20.0s exactly**. The ~2s difference is the venue's match timestamp vs our
  decision timestamp — not a second gate. The delay binds perfectly: 2,621 `PF_TE_WHALE_DELAY`
  events, p50 tl 29.1, and **85% of all live fires land in the single second the gate opens**.

---

## 2. Q1 — the accuracy-vs-time-left curve, rebuilt (and §33 corrected)

53.6k relay-lagged scans per tl-second, 7 coins, `cov>=0.5`, estimator error measured against the
final TWAP margin from `barrecon`.

| tl | mean abs est. error (bps) | p90 error | side accuracy | wrong 1 in… |
|---|---|---|---|---|
| 3 | 0.063 | 0.151 | 99.36% | 157 |
| 5 | 0.145 | 0.340 | 99.16% | 119 |
| 8 | 0.269 | 0.631 | 98.83% | 86 |
| 10 | 0.352 | 0.826 | 98.63% | 73 |
| 12 | 0.435 | 1.015 | 98.38% | 62 |
| **14** | **0.518** | 1.210 | **98.07%** | **51.9** |
| 16 | 0.602 | 1.402 | 97.81% | 46 |
| 18 | 0.686 | 1.597 | 97.48% | 40 |
| 20 | 0.769 | 1.784 | 97.28% | 37 |
| 24 | 0.931 | 2.122 | 96.85% | 32 |
| 30 | 1.148 | 2.632 | 96.27% | 27 |

### ⚠️ §33's headline number is wrong by ~17×
> §33: *"the T-14 estimator has mean |error| 0.025 bps and calls the SIDE wrong 1 time in 864 (0.12%)."*

Measured on 9 days / 7 coins / 53,563 relay-lagged scans: at tl=14 the mean |error| is
**0.518 bps** (20× larger) and the side is wrong **1 in 51.9 (1.93%)**, not 1 in 864.
The error grows almost exactly linearly at **~0.042 bps per extra second of tl**.
§33 was measured on 4,791 archive bars with a different (last-value-carry) estimator and no relay
gate; the arithmetic intuition ("48 of 59 ticks already exist") is right, but the residual from the
11 missing ticks is ~0.5 bps, not 0.025.

**What §33 got right and still holds:** accuracy is a function of MARGIN, not of vol, and clear
bars are callable at any horizon.

Accuracy by tl × |final margin| (the §33 cut) and by |live est| (the tradable cut):

| tl | \|margin\|<0.5 | 0.5-1 | 1-2 | 2-5 | ≥5 bps |   | \|est\|<0.5 | 0.5-1 | 1-2 | 2-5 | ≥5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 89.5 | 98.8 | 99.4 | 99.9 | **100.0** | | 89.5 | 98.9 | 99.4 | 99.9 | **100.0** |
| 8 | 79.7 | 97.6 | 99.4 | 99.9 | **100.0** | | 81.6 | 96.8 | 99.0 | 99.8 | **100.0** |
| 14 | 71.4 | 92.8 | 98.4 | 99.8 | **100.0** | | 74.3 | 93.3 | 97.3 | 99.7 | **100.0** |
| 20 | 64.7 | 85.6 | 95.7 | 99.3 | **100.0** | | 67.0 | 85.2 | 95.4 | 99.2 | **100.0** |
| 30 | 63.1 | 80.4 | 91.7 | 97.9 | **99.95** | | 66.2 | 79.9 | 90.4 | 97.8 | **99.93** |

### By-product: the live threshold ramp is close to iso-accurate, and raising it is refuted
Live gate `thresh(tl) = 0.5 + 0.035·max(0, tl−14)`. Accuracy realised at that gate: 99.85% (tl 3),
99.31% (14), 99.02% (20), 98.70% (30) — a gentle decay. A true iso-99% gate would want
0.29 @14 → 0.69 @20 → 1.38 @30 (slope ≈ 0.069). But **§37's proposed "next lever"
(`PM_TE_THRESH_SLOPE` 0.035 → 0.09) is REFUTED in the replay**: at `tl<=20`,
slope 0.035 / 0.07 / 0.09 → **+$20.07 / +$15.56 / +$14.57** per day (sweep cell) and
+$4.56 / +$0.44 / +$0.03 (strict cell). A stricter, blunter gate on a slice that is already
99% accurate only removes profitable volume. Same conclusion as §31's slope-gate refutation.

---

## 3. Q2 — accuracy × availability × price. Later is *not* strictly better.

Per gate-passing 0.4s scan (the bot's actual decision opportunities), bar-clustered SEs:

| tl band | gate-passing scans | **tape-confirmed fill available** | median displayed depth | mean ask | accuracy | EV per $24 clip ± SE |
|---|---|---|---|---|---|---|
| 3-8 | 7,627 | **7.1%** | $26 | 0.952 | 95.4% | +$0.08 ± 0.60 |
| 9-12 | 6,967 | **13.9%** | $26 | 0.938 | 95.5% | +$0.54 ± 0.40 |
| 13-16 | 9,221 | **18.2%** | $30 | 0.951 | 95.6% | +$0.10 ± 0.28 |
| 17-20 | 12,292 | **23.3%** | $35 | 0.957 | 97.1% | **+$0.40 ± 0.17** |
| 21-24 | 16,048 | 19.4% | $37 | 0.956 | 96.3% | +$0.20 ± 0.18 |
| 25-31 | 25,152 | 23.8% | $38 | 0.960 | 96.4% | +$0.10 ± 0.15 |

Three things to read off this table.

1. **Supply dies, hard and early.** Fill availability at tl 3-8 is **less than a third** of tl 17-20,
   and it is already down 40% by tl 9-12. Displayed depth also thins ($38 → $26).
2. **Accuracy conditional on a fill being available is FLAT (95.4-97.1%).** This is the finding
   that closes the lane. The steep unconditional curve in §2 does not transfer, because the
   population that offers you a cheap ask is adversely selected — the same one-book mechanism as
   [[taker-side-adverse-selection]] (`ua ≡ 1−db`).
3. **Waiting does not buy price.** Mean ask 0.938 (9-12) vs 0.957 (17-20) is a small population-level
   discount, and it vanishes on the bars that matter: on bars that *survive* to tl≤14, the live
   `seen_ask` median 0.980 becomes a later ask median of **0.990** (mean delta −0.0001, n=16,697).

### The decisive availability measurement (venue truth, not a replay)
Of the **778 bars the fleet actually filled at tl 17-20**, how many would still have offered a
gate-passing, **tape-confirmed** clip later?

| still fireable at | bars surviving | share | live PnL of survivors | live loss bars kept | median later ask |
|---|---|---|---|---|---|
| tl≤16 | 232 / 778 | **29.8%** | $107.07 of $66.04 | 7 / 25 | 0.990 |
| **tl≤14** | 140 / 778 | **18.0%** | $102.41 of $66.04 | 5 / 25 | 0.990 |
| tl≤12 | 91 / 778 | **11.7%** | $76.81 of $66.04 | 3 / 25 | 0.980 |
| tl≤10 | 56 / 778 | 7.2% | $59.83 of $66.04 | 3 / 25 | 0.980 |

§65 measured 68.8% persistence tl18→tl13 from **displayed** asks. Tape-confirmed it is **18%**.
That single correction removes the entire "+$3.8/day naive shift" estimate.

(The survivor set does look better — it carries >100% of the PnL and only 5 of 25 loss bars, i.e.
the vanishing bars are net negative. That is a genuine selection effect, but it is **not
harvestable**: the survivors' later ask is 0.99, so re-entering them late converts a 0.98 entry
into a 0.99 entry, and the end-to-end replay in §4 prices exactly that and comes out flat-to-worse.)

---

## 4. Q3 — the table: tl≤20 vs 16 vs 14 vs 12, with loss-bar counts

Replay, 09-02…09-09 (8 complete UTC days), all 7 coins, net of the taker fee.
Baseline is **tl≤18** (the live empirical ceiling; tl≤20 is shown for completeness — the two are
statistically identical, Δ = +$1.97/day, CI [−15.95, +18.76]).

### (a) sweep-permitting cell (primary — calibrates to live)

| gate | clips/day | bars/day | **loss bars/day** | loss rate/bar | stake | fee/day | net $/day | ROI | pos days | worst day | Δ vs tl≤18 (95% CI) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tl≤20 | 131.1 | 117.2 | **4.88** | 4.16% ±0.65 | $20,528 | $7.82 | +$20.07 | 0.78% | 4/8 | −$57.59 | +1.97 [−15.95, +18.76] |
| **tl≤18 (base)** | 87.6 | 79.2 | **3.38** | 4.26% ±0.80 | $13,841 | $5.48 | **+$18.10** | 1.05% | 5/8 | −$55.42 | — |
| tl≤16 | 66.2 | 61.2 | **3.00** | 4.90% ±0.97 | $10,257 | $4.47 | +$6.62 | 0.52% | 5/8 | −$52.86 | **−11.49 [−22.19, −1.39]** |
| tl≤14 | 45.5 | 43.2 | **2.25** | 5.20% ±1.19 | $7,230 | $3.40 | +$7.54 | 0.83% | 5/8 | −$51.17 | −10.57 [−27.73, +8.68] |
| tl≤12 | 32.0 | 31.5 | **1.75** | 5.56% ±1.44 | $5,021 | $2.76 | +$8.67 | 1.38% | 4/8 | −$16.20 | −9.44 [−33.24, +16.03] |
| tl≤10 | 20.8 | 20.8 | **1.00** | 4.82% ±1.66 | $3,507 | $2.05 | +$8.40 | 1.92% | 3/8 | −$22.77 | −9.70 [−32.88, +14.04] |

### (b) strict 0¢ cell (conservative bound)

| gate | bars/day | **loss bars/day** | loss rate/bar | net $/day | ROI | worst day | Δ vs tl≤18 (95% CI) |
|---|---|---|---|---|---|---|---|
| tl≤20 | 117.2 | 4.88 | 4.16% | +$4.56 | 0.18% | −$65.34 | +1.71 [−15.77, +19.34] |
| **tl≤18 (base)** | 79.2 | 3.38 | 4.26% | +$2.84 | 0.16% | −$63.08 | — |
| tl≤16 | 61.2 | 3.00 | 4.90% | −$4.34 | −0.34% | −$64.75 | −7.19 [−18.58, +3.92] |
| tl≤14 | 43.2 | 2.25 | 5.20% | +$0.21 | 0.02% | −$52.37 | −2.63 [−21.02, +18.26] |
| tl≤12 | 31.5 | 1.75 | 5.56% | +$3.98 | 0.63% | −$23.46 | +1.13 [−21.62, +25.90] |
| tl≤10 | 20.8 | 1.00 | 4.82% | +$6.07 | 1.38% | −$23.07 | +3.23 [−18.89, +27.21] |

CIs are a paired cluster bootstrap over the **56 (coin, day) cells**, 4,000 draws.
Per-day bar-clustered SE at the baseline is **±$15-17/day** — the whole sweep sits inside one SE.
Worst leave-one-out fold, tl≤18 sweep cell: LOO-day min +$9.53/day, LOO-coin min +$11.55/day
(both positive). At tl≤16 both LOO folds go negative (−$0.94 / −$0.41).

### The one effect that *is* measured reliably — and why it is not a reason to tighten
Loss-bars/day falls monotonically (4.88 → 3.38 → 3.00 → 2.25 → 1.75 → 1.00).
**But the loss RATE per bar does not fall — it drifts up** (4.16% → 4.26% → 4.90% → 5.20% → 5.56%).
Tightening removes losses only by removing *volume*, not by removing *bad* volume. It is a
position-size cut wearing a timing costume, and a plain clip-size cut is cheaper, instantly
reversible and does not touch behaviour. Compare [[bid-drop-veto]], which cuts the loss *rate*.

### Cross-check on the live ledger (drop clips above X, no re-laddering — a floor on the cost)
| gate | bars/day | loss bars/day | net $/day | fee/day | pos days | worst LOO-day | worst LOO-coin |
|---|---|---|---|---|---|---|---|
| tl≤20 (actual) | 96.4 | 3.00 | +$15.61 | $4.07 | 8/10 | +$3.66 | −$0.73 |
| tl≤18 | 30.5 | 1.10 | +$9.76 | $1.32 | 5/10 | −$1.05 | −$0.39 |
| tl≤16 | 20.6 | 0.70 | +$8.34 | $1.02 | 6/10 | −$2.13 | −$1.11 |
| tl≤14 | 12.2 | 0.20 | +$13.76 | $0.65 | 9/10 | +$4.98 | +$5.72 |
| tl≤12 | 7.6 | 0.20 | +$9.32 | $0.48 | 9/10 | +$0.22 | +$1.44 |

Same shape, from a completely different instrument: **no monotone gain, and every tighter gate
gives up more $/day than it saves.** (It also flatters tightening, since it drops the tl 19-20
clips without letting the bar re-fire — and it *still* loses money.) The fee saving is real
($4.07/day → $0.65/day) but you forfeit ~87% of the bars to bank $3.4/day of it.

---

## 5. Q4 — where does the budget bind? It doesn't.

| | clips/bar | bars with ≥2 clips | bars at the $48 cap | mean $ spent | **unused $/bar** |
|---|---|---|---|---|---|
| **LIVE (event ledger, 10d)** | **1.04** | **3.9%** | **1.9%** | **$19.2** | **$28.8** |
| replay tl≤30 | 1.20 | 19.4% | 11.0% | $23.4 | $24.6 |
| replay tl≤20 | 1.12 | 11.8% | 6.3% | $21.9 | $26.1 |
| replay tl≤16 | 1.08 | 8.2% | 4.9% | $21.0 | $27.0 |
| replay tl≤14 | 1.05 | 5.2% | 4.3% | $21.0 | $27.0 |
| replay tl≤12 | 1.02 | 1.6% | 1.2% | $20.0 | $28.0 |

**§33's mechanism is refuted at the current sizing.** It was written when
`WHALE_LADDER_USD=16` (2 clips of $8) and the ladder genuinely exhausted early. At **$24/$48**
the fleet takes **one clip per bar** and leaves **$28.8 of $48 unspent**. There is no budget to
"shift later" — the constraint is takeable supply, and moving the window later makes supply worse,
not the budget freer. (Consistent with §65-2: the $48 cap raise was refuted for the same reason
from the other side.)

---

## 6. Q5 — the freshness race changes queue position, never the call

Measured relay lag `t − cl_ts` on 1.41M snaps: **p10 1.55s / p50 2.15s / p90 2.80s** — confirms the
documented 2.21s.

Test (accuracy only — the race itself is explicitly not measured): recompute the estimate with the
TWAP window ending at wall-clock `t` instead of `cl_ts`, i.e. **every tick already stamped**,
≈ +2.15s of information — slightly *more* than the 2.07s Binance-vs-relay advantage.
⚠️ This variant is clairvoyant for PnL (bug #25) and is used here **only** as an accuracy measurement.

| population | tl 3-8 | 9-12 | 13-16 | 17-20 | 21-24 | 25-30 |
|---|---|---|---|---|---|---|
| **live-fireable** scans (|est| ≥ gate, ask 0.55-0.99), n=74,647 — side flips | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** | **0.0%** |
| all gate-eligible scans (incl. sub-threshold) — accuracy delta | +0.08 pp | +0.13 pp | +0.25 pp | +0.20 pp | +0.19 pp | +0.13 pp |

**Zero side flips in 74,647 live-fireable scans.** Mechanism: 2 extra ticks out of 59 is 3.4% of the
average; at |est| ≥ 0.5 bps that cannot move the sign. The +0.1-0.3 pp on the full population lives
entirely in the sub-threshold slice we never fire on.

⇒ Freshness is **worth nothing for accuracy at any tl**. Whatever the Kyiv/Helsinki latency work is
worth, it is worth it for *queue position on a call we would have made anyway* — which is exactly what
[[latency-execution]] already says ("location buys the RACE, not signal accuracy"). Accuracy channel: **REFUTED**.

---

## 7. What is NOT closed by this

* **tl 9-12 is the best per-clip band in both instruments** (replay +$0.54 ± 0.40 per $24 clip;
  live ledger +6.8% ROI on 74 fills, 0 loss bars in the 11-12 second). It is also the least
  reachable (13.9% availability vs 23.3%). Nothing here says "don't fill at tl 10" — it says
  "don't *wait* for tl 10", which is a different instruction. Firing whenever the gate opens
  already harvests this band whenever it appears.
* The `tl<=12` vs `16-20` question **remains undecidable live** (§73c: per-bar ROI sd 17.4pp ⇒
  ~858 coin-days per arm). This replay agrees: every Δ but one has a CI spanning ±$25/day.
  Neither instrument will ever settle it; the mechanism arguments (flat conditional accuracy,
  18% persistence, unused budget) are what settle it.
* The loss tail is still the fleet's problem (09-09: −$66.93 in a day). It is **not** a timing
  problem — the loss rate per bar is flat in tl. It is a *selection* problem, which is
  [[bid-drop-veto]]'s lane, not this one.

## 8. Config change if shipped

**None.** Leave `PM_TE_WHALE_VOL_DELAY_TL = 20` and `PM_TE_WHALE_VOL_DELAY_VOL = 0.01` exactly as
deployed. §37 was right and is doing its job (2,621 delay events over 10 days, 0 fires above
tl 20). Do not add `pmTeWhaleVolDelayTl: "14"`. Do not raise `PM_TE_THRESH_SLOPE`.

## 9. Bug-ledger candidates

* **Persistence statistics must be tape-gated too.** §65's 68.8% (displayed) vs 18.0% (tape-confirmed)
  is bug #23 appearing in a *derived* statistic rather than in a fill count. Any "would the
  opportunity still be there later?" number computed from displayed asks is ~4× too high.
* **`polysim2.py`'s `thresh=0.10` default is not the live gate** (`pmTeThreshBps: "0.5"` on all 7
  coins). At `thresh=0.10` the replay admits ~20% more candidate rows than the fleet ever sees.
* **A 1Hz panel under-samples a 0.4s scan loop by 2.5×** and halves the replayed bar count.
  Any availability or clip-count claim must be built at the loop's own cadence.

## 10. Reproduce

Scripts in the session scratchpad (`agentB/`): `panel04.py` (0.4s panel), `h2.py` (house-cell
replay), `acc.py` / `run11.py` (accuracy curve, iso-accuracy schedule), `run7.py` (availability ×
price × EV), `run13.py`/`run14.py` (bootstrap + LOO), `fresh.py` (Q5), `liveled.py` +
`persist.py` (live pod ledger, read-only, and the persistence measurement).
No bot config was edited, nothing deployed, nothing committed.
