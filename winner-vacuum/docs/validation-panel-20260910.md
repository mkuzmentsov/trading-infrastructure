# Panel validation — 2026-09-10 rebuild (Agent E, gatekeeper)

**PANEL SUSPECT — the settlement/book/tape layers validate, but the replay pipeline built on
them cannot reproduce the live policy and gets the SIGN wrong: −$82 gross where the fleet made
+$203 over the same 8 days. Three named defects (§2b, §3, §8a) make every $/day number and every
tail/veto finding produced on this panel unreliable until they are corrected. The tail is the
worst-served region: the replay reproduces only 2 of the 7 real 09-09 loss bars.**

**What still stands:** the settlement arithmetic (99.40%, band-for-band vs prior ground truth),
the print tape, and the book *at the decision second* (99.7% presence, 100% on loss bars). Rate-
and base-rate findings survive with the §4 filters; dollar and loss-tail findings do not.

Scope: parquet at `every-tick-single/data/pq`, built 2026-09-10 23:30-23:43 from the 9-day
drain. Ground truth: `winner-vacuum/RESEARCH-LOG.md` day closes **plus** — new in this
validation — the fleet's own `PF_TE_WHALE_ORDER` ledger pulled read-only from all 7 live pods
(1,994 fires / 1,141 fills, 09-01→09-10). That ledger reconciles the RESEARCH-LOG day closes to
**within $0.55 on every day**, so it is a strictly better instrument than the log and is used as
ground truth throughout.

---

## 0. Headline: what is trustworthy and what is not

| layer | verdict | evidence |
|---|---|---|
| `res` / `bar` resolutions | ✅ sound, but **holed** (§4) | 0 dup (coin,ws); 6-hour resolution outage 09-09 18:55→09-10 00:55 |
| `cl` / `barrecon` TWAP-60 settlement arithmetic | ✅ **VALIDATED** | 99.40% vs prior ground truth 99.48%, band-for-band (§1) |
| `trades` print tape | ✅ sound | 5.51M prints, 0 dup tx, arrival lag p50 0.03s |
| `snapcur` / `panel` book **presence** at the decision second | ✅ **VALIDATED** | panel shows a favourite ask at 99.7% of real live fires — **100% on loss bars** (§2a, §8a) |
| `panel` book **price fidelity** on violent bars | ⛔ **DEFECT 3** | 1 row/second retention: ask matches the bot's within 0.5¢ on 70.6% of quiet fires but only **15.1%** of sweep fires (§8a) |
| `panel.est_bps` — the relay-lagged live estimate | ⛔ **DEFECT 1** | disagrees on side with the bot's own estimate on **10.6%** of real fires; on those the bot was right 92.6% (§2b) |
| the house fill cell (0.4s / 0¢ / top-3) | ⛔ **DEFECT 2** | structurally cannot represent **44% of the fleet's gross** (§3) |
| **any $/day figure from a replay** | ⛔ **DO NOT QUOTE** | best cell reads −$82 vs live +$203 (§5) |
| **any per-bar tail / veto finding scored on a replay** | ⛔ **DO NOT SHIP** | replay reproduces only **2 of 7** real 09-09 loss bars; 3 of its 5 are fictional (§6) |
| aggregate loss-**bar count** | ⚠️ coincidentally close | 27-32 sim vs 30 live over 09-02…09-09, but different bars |

---

## 1. Positive control 1 — recon accuracy: **PASS**

`barrecon.parquet`, 18,339 bars, 18,266 with a reconstructable margin.

| \|margin\| bps | n | acc (new build) | prior ground truth (offline-notes L2101, 9,773 bars) |
|---|---|---|---|
| overall | 18,266 | **0.9940** | 0.9948 |
| 0 – 0.1 | 150 | 0.7000 | 0.729 |
| 0.1 – 0.25 | 227 | 0.8899 | — |
| 0.25 – 0.5 | 400 | 0.9775 | 0.972 |
| 0.5 – 1 | 758 | 0.9868 | — |
| 1 – 2 | 1,436 | 0.9916 | 0.994 |
| 2 – 5 | 3,709 | 0.9978 | — |
| ≥ 5 | 11,586 | 0.9999 | 1.000 |

Per coin 0.9929–0.9952; per day 0.9911–0.9975; no day or coin is an outlier.
Tick completeness `sobs`/`fobs` = 55.0/59 mean (≈7% of Chainlink ticks missing from the
recorder's capture — unchanged from prior builds, and the cause of the 0-0.1bps band's 70%).

**The new build agrees with prior ground truth band-for-band.** One correction to the task
brief: the established "~93% below 0.25bps" is not what the docs say. The documented prior is
**72.9% at 0-0.1bps** (offline-notes L2101); the new build reads 70.0%. Both builds are ~81%
over the whole sub-0.25 region. No discrepancy.

---

## 2. Direct panel validation against the live pod ledger

This is the check nobody had run. For each of the 1,047 real filled fires I joined the panel row
at `(coin, ws, tlk=ceil(tl))` and compared it to what the bot actually logged.

### 2a. Book state — **PASS**
- panel has a `fav_ask` at the fire second: **99.45%** of all fires, **99.81%** of filled fires
  (2 misses in 1,047).
- `|panel fav_ask − bot seen_ask| ≤ 0.005` on 72.5% of them; median difference **exactly 0.000**.
- Holds on every day (99.2-100%) and every ask band including 0.55-0.80.

⚠️ Do **not** be alarmed by "only 10.9% of panel rows in tl 4-20 have a `fav_ask`". That is the
documented physics (`ua ≡ 1−db`; the favourite has no ask when it is the near-certain winner),
not a defect. The bot only fires in the seconds where an ask exists, and the panel has those
seconds. Any statistic of the form "asks became scarcer" computed over *all* panel rows is the
§72 ghost-quote trap again — the 09-04 apparent 3.4× drop in `fav_ask` presence is an artefact of
the side mix, not of the book. Raw `ua`/`da` presence is flat at 51-63% across all 9 days.

### 2b. The live estimate — ⛔ **DEFECT 1**

| metric | value |
|---|---|
| corr(panel `est_bps`, bot `est_bps`) | 0.9940 |
| median \|panel − bot\| | **0.34 bps** — against a **0.5 bps** live gate |
| p90 \|panel − bot\| | 1.45 bps |
| **side disagreement** | **10.6%** of real fires (108 / 1,047) |
| on those 108: bot side correct | **92.6%** |
| on those 108: panel side correct | **7.4%** |
| panel `|est| ≥ eff_thresh` gate pass-rate on real fires | **71.7%** |

So **28% of the fleet's real decisions are not reproducible from this panel** — the panel's
reconstruction of the estimate simply fails the live gate. And on the 10.6% where it takes the
other side, it is the panel that is wrong, not the bot.

**This is NOT bug #25 (relay-lag clairvoyance).** I tested that directly by recomputing the
estimate with the `cl_ts` gate removed entirely and with 1/2/3s of extra lag:

| variant | median \|err\| vs bot | side disagreement | mean ticks |
|---|---|---|---|
| `panel.py` as built | 0.393 | 0.106 | 40.7 |
| no lag gate at all (clairvoyant) | 0.340 | 0.082 | 41.9 |
| +1s lag | 0.375 | 0.098 | 41.0 |
| +2s lag | 0.408 | 0.109 | 40.0 |
| +3s lag | 0.443 | 0.119 | 39.1 |

`panel.py`'s lag handling is **correct** — it sits ~1.2 ticks short of the clairvoyant bound and
costs only ~2pp. The residual error is intrinsic: the recorder's 1Hz Chainlink capture is a
*different tick set* from the bot's own feed (≈7% of ticks missing), and at a 0.5 bps gate a
0.34 bps reconstruction error straddles the decision constantly. Disagreement is worst exactly
where the policy lives: **13.5% at \|est\| 0.5-0.75 bps and 15.5% at 0.75-1.0 bps**, falling to
5% above 2 bps.

### 2c. Side instability *within* a bar — corollary defect

`panel.side` flips at least once over tl 4-32 in 4.0% of all bars — but:

| bar class | n | mean flips | ≥1 flip |
|---|---|---|---|
| bars the fleet **LOST** | 32 | 0.63 | **46.9%** |
| bars the fleet won | 983 | 0.20 | 19.8% |
| bars never traded | 17,311 | 0.03 | 3.1% |

Every `fav_*` column is `where(side=='UP', u…, d…)`, so when the side flips the column silently
switches token and the value jumps to roughly its complement. Any *lagged* book feature is
therefore comparing two different instruments across the lag.

For `panelflow2.dbid10` this is measurable: 1.30% of rows have a side flip across the 10s lag,
and on those `|dbid10|` has median **0.87** (89% exceed 0.30). The good news for the bid-drop
work: of all large drops (`dbid10 ≤ −0.30`, n=2,288) only **2.6%** are flip artefacts, so the
signal is 97.4% clean in aggregate. The bad news: the flip rate on live loss bars is 47%, so a
veto validated on the tail **must** carry a `side[t] == side[t−lag]` filter or it is partly
measuring a token switch. Cheap fix, but it is not currently in `flow2.py`.

---

## 3. ⛔ DEFECT 2 — the house fill cell truncates the right tail and keeps the left

The live FAK is **dollar-denominated at the venue, not share-denominated**. `twapedge.py:1325`
requests `int(min(26, 24/ask))` shares, but the matching engine spends up to that notional and
returns whatever the book gives. Measured on the live ledger:

| | bars | gross | wins | losses |
|---|---|---|---|---|
| normal fills (≤30 sh) — **all the house cell can ever produce** | 976 | **+$122.82** | 951 | 25 |
| **sweep bars** (>30 sh; FAK ate a stale/collapsed book) | **39** | **+$95.01** | 32 | 7 |
| total | 1,015 | +$217.84 | 983 | 32 |

**39 bars = 3.8% of the population carry 44% of the era's gross** (+$234.19 of wins against
−$139.18 of losses; max 1,524 shares on one $23 clip). The house cell's "price improvement 0¢,
fill AT the displayed ask, size walked down the displayed top-3 ladder" caps a bar at ~30 shares.
It therefore **removes the entire windfall lane while retaining the losses**, because a loss is
bounded by the dollar cost (~$24) and the sim reproduces that correctly.

That single asymmetry is sufficient to flip a replay's sign. It is not a bug in the panel; it is
a bug in the documented cell.

Supporting live fill physics the cell also mis-models:
- **22.4%** of live fills land **above** the displayed ask (the bot posts `ask + 1¢`, `LIVE_PX_BUFFER`). The cell charges the displayed ask.
- 6.8% land below; those 71 fills alone carry **$63.25 of $225.48** gross.
- 21.4% of fills are partial.
- Live **match rate is 57.2%** (1,141 fills / 1,994 fires) — the cell has no model of a fire that misses.

### 3b. The 0.4s tape-confirmation window has a 58% false-negative rate
Run the sim's gates over the 1,047 fires that *demonstrably filled on the venue*:

| gate (evaluated on real fills) | pass | gross retained |
|---|---|---|
| all real filled fires | 1,047 | +$225.48 |
| + panel `cov ≥ 0.5` | 1,033 (98.7%) | +$218.28 |
| + panel `\|est\| ≥ eff_thresh` | 751 (71.7%) | +$201.11 |
| + panel side == bot side | 717 (68.5%) | +$229.79 |
| + panel ask ∈ [0.55, 0.99] | 705 (67.3%) | +$272.29 |
| + ladder-min 0.94 | 649 (62.0%) | +$139.69 |
| **+ tape-confirm 0.4s** | **374 (35.7%)** | **+$71.69** |
| + tape-confirm 1.5s (for comparison) | 621 (59.3%) | +$129.94 |

The 0.4s window rejects **42% of fills that actually happened** (649→374). `last_trade_price`
events are coalesced by the venue, so a real fill frequently does not print inside 0.4s. Bug #23
is real and the tape gate is the right idea, but **0.4s is mis-calibrated**; 1.5s recovers 96% of
real fills (621/649) at the cost of admitting more phantoms.

---

## 4. Tape sanity — three real defects

1. ⛔ **6-hour resolution outage, 09-09 18:55 → 09-10 00:55 UTC.** `bar.parquet` has all 12
   bars/hour throughout, and the raw `.jsonl.gz` files are full-size — but the recorder emitted
   **1, 0, 6, 3, 3, 6 RES rows** in hours 19-23 / 00 (vs 12-13 normally). Verified at the source
   with `grep -c '"ev":"RES"'`, so it is a recorder-side resolution-poller failure, not a
   pipeline bug. Cost: ~57 bars/coin × 7 coins ≈ **400 unlabelled bars, and they land on the
   evening of 09-09 — the exact day the brief asks to reproduce.** The panel inner-joins on `res`
   and drops them silently.
   ⚠️ **Do NOT patch these with `barrecon.pred`.** The vacmaker edge *is* the recon prediction;
   labelling by recon and then scoring a recon-based policy gives a 100% win rate by construction.
2. ⚠️ **`zec` is in the panel (2,584 bars) and is not a traded coin.** `res.parquet` carries 8
   coins; the live fleet is 7. `zec` has no Chainlink series (absent from `barrecon`), so
   anything computed over "all coins in the panel" silently includes an untraded instrument.
   `snap2pq.py`'s coin list excludes it but `ev2pq.py`'s does not.
3. ⚠️ **bnb and doge carry an 08-25/08-26 tail** (124 bars) plus a full 09-01 (288 bars vs 48-49
   for the other five). Different era, different config. Filter to `ws ≥ 2026-09-01 20:00 UTC`
   before any cross-coin comparison, or bnb/doge get 6× the 09-01 weight of everyone else.
4. Minor: 09-03 is short 1-4 bars/coin; 09-10 hour 00 is thin (3-7 bars) — a recorder restart.
   09-01 (partial, 20:00→) and 09-10 (partial, →19:50) are boundary days: **use 09-02…09-09 only.**

---

## 5. ⭐ The calibration table — replay vs the fleet's own day closes

**Fill cell used (named as required):** `FILLW = 0.4s`, price improvement **0¢** (fill at the
displayed ask), size **walked down the displayed top-3 ask ladder restricted to levels priced
≤ the displayed ask**, tape-confirmed (a real BUY print at `px ≤ ask` inside the window), clip
`int(min(LIVE_SIZE_sh, LIVE_MAX_ORDER_USD/ask))` = $24/26sh (doge $5/5sh), ladder $48 (doge $4).
Policy taken from `winner-vacuum/src/twapedge.py::whale_loop` + the 7 live yamls, **not** from
`polysim2.py`: `tl ∈ (3,20]` (§37 delay, `pmTeWhaleVolDelayVol=0.01`), `cov ≥ 0.5`,
`eff_thresh = 0.5 + 0.035·max(0, tl−14)`, ask ∈ [0.55, **0.99**] (`pmTeWhaleCap` is unset
everywhere → default 0.99; `pmTeMaxAsk` is a *different* gate and does not bind here), §58
first-clip skip 0.90-0.98 (eth exempt), ladder-min 0.94, 8s cooldown, $30 daily halt with 1h
cooldown (xrp 999, doge 7), disloc budget $24.

**Accounting: GROSS on both sides.** The RESEARCH-LOG day closes are gross of the taker fee
(`twapedge.py:1345` computes `cost = avg_px·filled` with no fee term); `lib.py`'s `load_trades()`
is net. Comparing them directly costs ~$5/day.

| UTC day | LIVE gross | LIVE bars | LIVE loss | HOUSE 0.4s | bars | loss | 1.5s variant | bars | loss |
|---|---|---|---|---|---|---|---|---|---|
| 09-02 | −21.87 | 94 | 7 | −52.69 | 58 | 6 | −63.29 | 69 | 8 |
| 09-03 | +26.18 | 115 | 6 | −79.14 | 61 | 8 | −70.81 | 71 | 9 |
| 09-04 | +12.90 | 121 | 2 | +34.45 | 63 | 1 | +21.38 | 78 | 2 |
| 09-05 | +29.83 | 121 | 2 | +22.31 | 46 | 1 | +35.31 | 66 | 1 |
| 09-06 | **+129.16** | 117 | 2 | +18.55 | 61 | 2 | +8.24 | 80 | 3 |
| 09-07 | +31.09 | 129 | 2 | −5.86 | 62 | 2 | +23.21 | 71 | 2 |
| 09-08 | +63.10 | 155 | 2 | +24.47 | 77 | 2 | +26.56 | 97 | 2 |
| 09-09 | **−67.48** | 97 | 7 | −43.64 | 67 | 5 | −49.00 | 74 | 5 |
| **total** | **+202.91** | **949** | **30** | **−81.55** | **495** | **27** | **−68.40** | **606** | **32** |

(09-01 and 09-10 excluded as partial. Full table incl. a no-tape and a tape-price variant is in
the run log; the *best* of the four cells on PnL is "1.5s + tape print price", +$236 / 637 / 34 —
i.e. it overshoots by $33 and 4 losses while still missing a third of the bars.)

**Verdict on the calibration: FAIL.** No cell matches on all three axes. The house cell misses
**48% of the bars** and gets the sign wrong on the era. Note 09-06 in particular: live +$129.16,
of which the single bnb 0.238 sweep is +$77.82 — the replay reads +$18.55 because that bar is
structurally unreachable (§3).

### 5b. Is the published house-cell benchmark reproducible from the README as written?
**Two axes yes, PnL no.** Re-implementing exactly the polysim2 shape + the README cell (thresh
0.10, $24/$48, GAP 8, tape print at `px ≤ ask`, depth from the top-3 **restricted to levels
priced ≤ ask** — i.e. the strict reading the coordinator flagged), 09-02…09-04:

| | PnL | bars | loss bars |
|---|---|---|---|
| published benchmark | +$34.94 | 312 | 22 |
| this rebuild, strict reading | **−$91.65 gross / −$112.74 net** | **320** | **22** |
| this rebuild, loose reading (no px≤ask on depth) | −$198.49 | 320 | 22 |
| live (pod ledger, gross) | +$17.21 | 330 | 15 |

Bar count and loss-bar count reproduce to within 3%. **PnL does not, by $127**, and the strict
reading only moves it $107 of that. So the strict-vs-loose depth question is real and the README
should state it — but it does **not** account for the benchmark. Recommendations:
- `calib.py` must be committed. Right now the benchmark is unfalsifiable.
- The README should state (a) `px ≤ ask` binds on **both** the print and the depth walk, and
  (b) `polysim2.py`'s `thresh=0.10` is a **fourth** wrong default — the live gate is
  `pmTeThreshBps = 0.5`. Running at 0.10 inflates the bar count ~1.6× and is very likely why the
  published cell appeared to match live's 351 bars.

---

## 6. ⭐ Does the replay reproduce the 09-09 disaster? **NO — and this is the decisive failure**

Day-level it looks fine: replay −$43.64 / 67 bars / 5 losses vs live −$67.48 / 97 / 7. That
agreement is **coincidental**. Bar-for-bar:

**Real 09-09 loss bars (pod ledger):**

| coin | UTC | seen_ask | avg_px | shares | gross |
|---|---|---|---|---|---|
| eth | 10:30 | 0.76 | **0.107** | 186.7 | −20.02 |
| sol | 10:30 | 0.88 | **0.015** | **1,524.2** | −23.14 |
| btc | 13:30 | 0.85 | 0.780 | 28.7 | −22.36 |
| hype | 13:50 | 0.65 | **0.373** | 45.9 | −17.16 |
| xrp | 14:35 | 0.65 | 0.660 | 0.5 | −0.34 |
| sol | 14:45 | 0.99 | 0.990 | 7.4 | −7.29 |
| hype | 17:30 | 0.85 | **0.585** | 38.2 | −22.36 |

**Replay's loss bars:** sol 07:15, eth 11:40, btc 13:30, xrp 14:35, btc 16:40.

**Overlap: 2 of 7.** Five real losses are missing; three of the replay's five are bars the fleet
never lost on (btc 16:40 and eth 11:40 the fleet never even fired). Confirming the coordinator's
independent read: live's 09-09 damage is in the cheap band — 0.55-0.80 = −$32.02 and 0.80-0.90 =
−$59.84, against +$19.53 at 0.94-0.98 and +$0.88 at 0.98-0.99.

**Why**: 6 of the 7 real losses filled at `avg_px` far below the displayed ask — the §66
mechanism (violent impulse → our-side bid collapses → FAK sweeps a collapsed book). Era-wide,
**16 of 32 live loss bars (50%) are these stale-quote sweeps, carrying −$248.86 of −$479.71**,
and **14 of 32 filled more than 26 shares, carrying −$275.13**. The house cell fills 26 shares at
the *displayed* price. It cannot represent the event at all; it happens to book a similar dollar
loss on *different bars* because the ladder budget caps both at ~$24.

**Consequence, stated plainly:** the sim is blind to precisely the risk that matters most. Any
veto scored by "how many replay loss bars does it remove" is being scored against a loss
population that is ~70% fictional on the worst day of the era. The [[bid-drop-veto]] premise
survives (the panel *does* carry the collapsing bid — I read it back on all 7 real loss bars),
but its **$/day and losses/day must not be quoted from a replay**.

---

## 7. What to do (no config touched, nothing deployed, nothing committed)

**For the four agents reading this today:**
1. Findings of the form "cell X has effect Y bps / higher win rate / different base rate" —
   **still valid**, subject to §4's filters (drop `zec`, drop pre-09-01-20:00 bnb/doge, use
   09-02…09-09 only, and remember 09-09 evening is missing).
2. Findings of the form "**this veto is worth $N/day**" or "**this removes K loss bars/day**" —
   **not valid.** Re-express as a conditional rate on the real fill ledger, or state the number
   with the §3/§6 caveat attached.
3. Any feature built from a **lagged** `fav_*` column — add `side[t] == side[t−lag]` (§2c).
4. Anything gated at `|est| ≈ 0.5 bps` inherits a 0.34 bps reconstruction error and a 10.6%
   side-disagreement rate with what the bot actually did (§2b). Bucket at ≥1 bps where possible.

**Repairs, in priority order (none applied):**
1. Score replays against the **pod ledger**, not the RESEARCH-LOG. It is one `kubectl exec` per
   pod (`grep PF_TE_WHALE_ORDER /app/logs/logs-training-events.jsonl*`), reconciles the day
   closes to <$0.55, and needs **no fill model at all**. Extraction script:
   `scratchpad/live/*.jsonl` → `live_fires.parquet` (this session).
2. Re-calibrate the fill cell with a **sweep model**: on a fire, allow the fill to walk the real
   print tape below the displayed ask up to the dollar cap. Without it no cell can be positive.
3. Fix the 0.4s tape window (58% false negatives on real fills); 1.5s is the measured floor.
4. Backfill the 09-09 evening resolutions from gamma (`bar.parquet` has the slugs) — **from the
   venue, never from `barrecon`**.
5. Commit `calib.py`; state `px ≤ ask` on both print and depth in the README; add
   `polysim2.thresh=0.10` to the wrong-defaults list.
6. Recorder: alert on RES-row starvation (the 09-09 outage ran 6h undetected while every other
   health signal was green).

**Bug ledger candidates:** #43 dollar-denominated FAK ⇒ the house cell truncates the right tail
(§3). #44 `panel.side` flips mid-bar ⇒ lagged `fav_*` features switch token (§2c). #45 0.4s
tape window has a 58% false-negative rate on real fills (§3b).

---

## 8. Two challenges from other agents — adjudicated

### 8a. "The 1Hz panel under-samples the 0.4s live loop and halves the bar count"
**Half right, and the half that is wrong is the reassuring half.** `panel.py` keeps one snap per
(coin, bar, tl-second) — the *first* in each 1-second ceiling bucket — out of a ~10Hz recorder,
while `WHALE_SCAN_S = 0.15` (not 0.4; `pmTeWhaleScanS: "0.15"` in all 7 yamls) gives the bot
~6-7 looks per second.

Tested directly against the 1,057 real fires:

| population | n | panel has the ask at that second | panel ask within 0.5¢ of `seen_ask` |
|---|---|---|---|
| all real fires | 1,057 | **99.72%** | 63.9% |
| **live-LOSS bars** | 35 | **100.00%** | **22.9%** |
| live-WIN bars | 1,022 | 99.71% | 63.9% |
| bars with ≥1 mid-bar side flip (violent) | 221 | 99.55% | 32.1% |
| bars with no side flip (quiet) | 836 | 99.76% | **70.6%** |
| **sweep fills** (`avg_px < seen_ask`) | 73 | **100.00%** | **15.1%** |
| cheap band (`ask ≤ 0.90`) | 94 | **100.00%** | 17.0% |
| `ask ≥ 0.94` | 958 | 99.69% | 67.2% |

**Answering the coordinator's question directly: the under-sampling does NOT preferentially miss
violent bars — it misses them least often (100% presence on loss bars and on sweeps).** There is
no optimism bias from *dropped* bars, and therefore no reason to think loss-tail conclusions are
biased toward optimism by sampling alone.

**But** the failure mode is real and worse in a different way: on violent bars the panel keeps the
row and carries the **wrong price in it**. Within the second in which the book collapses, the
retained snap agrees with what the bot saw only 15-23% of the time versus 71% on quiet bars. So a
replay's *entry price on precisely the tail bars* is close to arbitrary. Rebuilding at 0.4s (or
better, event-time) cadence is worth doing — but it buys **price fidelity, not bar count**.

I could not reproduce "halves the bar count" from sampling: at the live gate the panel yields
**1,194 candidate bars** against **1,015 real live-filled bars** — already more opportunities than
live took, before any extra scan resolution. In this implementation the ~50% bar shortfall is
fully accounted for by the tape gate (58% false negatives, §3b) and the estimate gate (28%, §2b).
Both measurements can be true if the other agent's 0.4s rebuild also relaxed one of those; worth
reconciling, but sampling is not the binding constraint on bar count here.

**Practical answers:**
- Adequate for **relative A/B** (veto on/off, gate X vs Y) **on quiet bars** — yes.
- Adequate for relative A/B **on the loss tail** — **no**, because the tail bars are exactly where
  entry price fidelity collapses (§8a) *and* where the fill model is structurally wrong (§3).
- Adequate for any **absolute $/day** claim — **no** (§5).

### 8b. §33's "at tl=14 the side is wrong 1 in 864" — **REFUTED, independently**

Measured straight off `panel.est_bps` vs the realized winner, 7 live coins, all bars:

| tl | population | n | wrong-side rate | = 1 in |
|---|---|---|---|---|
| 14 | all bars | 18,197 | 1.73% | **57.8** |
| 14 | `cov ≥ 0.5` | 17,876 | 1.70% | 58.8 |
| 14 | `cov ≥ 0.5` & `|est| ≥ 0.5bps` (**the live gate**) | 17,087 | 0.59% | **169.2** |
| 14 | `cov ≥ 0.5` & `|est| ≥ 1bps` | 16,368 | 0.32% | 308.8 |
| 20 | all bars | 18,172 | 2.61% | 38.3 |
| 20 | live gate | 17,026 | 1.18% | **84.7** |

Mean `|panel est(tl=14) − final margin|` = **0.460 bps** (median 0.294) — **18× the 0.025 bps**
§33 asserts, and in exact agreement with the documented 0.46 bps proxy-noise figure. My unconditional
1-in-57.8 corroborates the entry-timing agent's 1-in-51.9 by a different method (panel vs their
relay-lagged scan set).

**§33's "settlement is arithmetic, the side is wrong 1 in 864 at tl=14" is wrong by ~15×
unconditionally and ~5× even after the live gate.** The operational number to carry forward is
**1 in 169 at tl=14 and 1 in 85 at tl=20, under the deployed gate**. This matters beyond
bookkeeping: at ~30:1 payoff, a 1-in-169 wrong-side rate is roughly break-even on the estimate
alone, so the fleet's edge cannot be "the arithmetic is certain" — it must be the ask price paid.
The brief handed to every agent this morning carries the 1-in-864 figure; it should be corrected
before anything is built on it.
