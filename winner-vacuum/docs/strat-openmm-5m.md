# strat-openmm-5m — two-sided MAKER quoting at .44–.56, first 60s of the 5m bar

Created 2026-08-19 (session: "make a maker strategy work on 5m"). Status:
**⛔ DEAD ON THE LATENCY GATE — NOT deployed, do not deploy.** The economics
are real at a 100ms quote cycle (+$44–125/day, pair engine t=+8.7, 19/19 days
positive) but the venue's measured order round trip is **190ms median**, and
at that speed EVERY configuration loses (−$64…−$191/day). See §10.
User constraint: must be a genuine mid-price (.40–.60) maker strategy, not
another tail/vacuum variant.

Dataset: local mrec archive `every-tick-single/data/mrec/<coin>/`, 07-30 →
08-17 (19 days), 100ms full-bar. Scripts: `every-tick-single/backtest/mm5m/`.

## 1. Why the old ⛔ verdicts did not close this

Every prior maker attempt (poolfarm, rewfarm, ask-ladders, mm-flip) quoted
**the whole bar** and/or **at any price band**. The field-wide terrain map
(`terrain.py`, every real print, maker side, no fill model) shows the maker
side of this venue is NOT structurally doomed — it is almost exactly
break-even in aggregate, and the losses are concentrated in specific cells:

| cut | maker net c/share |
|---|---|
| ALL 5m prints, btc, 193M shares | **−0.010** (gross −0.209 + rebate +0.199) |
| tl 60–120 (mid-bar) | −0.297 |
| tl 240–296 (**first minute**) | **+0.411** |
| tl 296–301 (first 4s) | −0.405 (stale pre-open orders swept at the open) |
| maker long .30–.45 | −0.387 |
| maker long .45–.55 | +0.035 |

Zero-sum check: taker gross alpha +0.209 c/sh vs 0.995 c/sh of fees paid ⇒
takers net −0.79 c/sh, makers −0.01, venue keeps the rest. Consistent.

**Control:** randomising the per-bar outcome gives +0.012 c/sh vs the real
−0.194 — the maker loss is real structure (informed flow), not label drift.
UP win rate 49.68%, mid at tl=0 tracks outcome at corr +0.863.

## 2. Mechanism — why this dodges the ONE WALL

The wall: *taker flow is informed; it lifts the eventual winner*. This design
does not rest against that flow directionally. It rests on **both** sides
simultaneously while the bar is still a coin-flip, so the guaranteed component
is a **pair**: buy UP at pxU + buy DOWN at pxD, pays exactly $1 at resolution.
Profit = `1 − pxU − pxD + rebates`, locked the moment both legs fill and
independent of who wins. The informed flow can only take us out of one leg.

## 3. Structural facts measured first (these killed the naive designs)

- **Spread is 1 tick 97.5% of the time.** There is nothing to capture by
  improving; you can only join a queue or cross. Effective tick is **1c** —
  `orderPriceMinTickSize=0.001` is real in the API but 100% of mid-range
  quotes AND prints sit on the 1c grid.
- **Touch queue 130–240 shares deep**, thinnest at the open (median 132–159).
- **Queue decay is fast** (`queuedyn.py`): cancellations 65–185 sh/s vs trades
  22–98 sh/s ⇒ standing queue half-life **1.3–2.3s**. A resting order does walk
  to the front; it does NOT only fill on sweeps.
- **Touch price dwell is short**: median 0.4–0.6s. Chasing is hopeless;
  the quote must be managed, not chased.

## 4. Fill model (calibrated, and it passes the validity controls)

Queue ahead = full displayed size at join, decaying at the measured rate only
while our level is the touch; trades consume queue-ahead first then us (FIFO);
a print through our level sweeps us; reaction delay on every place/cancel;
hold to resolution. Controls (docs/README §4):
- NOQ (queue ignored) is **better** than the calibrated run (+0.687 vs +0.251) ✓
- unconditional mid-quoting **loses** (−1.06 c/sh) ✓
- random-outcome control isolates selection, and the strategy's own RAND run
  reproduces the pure pair-arb component ✓

## 5. Dead ends closed this session (all sim-refuted, with the reason)

| idea | verdict | why |
|---|---|---|
| Sell the cheap tail (maker long .85–.96 mid-bar) | ⛔ | field-wide +0.9 c/sh, but **−0.41 c/sh under the queue model** (NOQ +0.50). Only fills when the level is swept. Also: it is a vacuum variant, out of scope. |
| Rest BELOW the touch to absorb sweeps | ⛔ −4.2 c/sh | the field's "+3.44 c/sh swept-deep" bucket is a **stale-snapshot artifact**: the bid had already moved down and those makers sat at the NEW touch. Classic ledger-#5 clairvoyance. |
| Complete unpaired legs with a TAKER order | ⛔ −$92/day | the pair ceiling only permits completion when the other side is cheap ⇒ **cuts winners, keeps losers**; and the taker fee peaks at exactly p=0.5 (1.75 c/sh) vs 0.78 c of pair profit. |
| Complete unpaired legs as a MAKER (+1 tick) | ⛔ −$9/day | pair% rises to 94% but the completing leg fills exactly when the market moves against us. |
| Quiet-market filter to buy latency tolerance | ⛔ | does not rescue 200–400ms (see §7). |

## 6. The configuration

Per coin, per bar:
- **Window** tl ∈ [240, 297] — the first minute, skipping the first ~3s
  (tl>297 is −0.405 c/sh: stale pre-open orders swept at the rotation).
- **Band**: quote only while the bid sits in **[0.44, 0.56]** — i.e. only while
  the bar is a genuine coin-flip. This is also where the rebate is maximal
  (fee ∝ p(1−p) peaks at 0.5 ⇒ 0.35 c/sh).
- **Both tokens**, joining the touch bid, re-pinned as the touch moves.
- **Spot pull**: stand down a side when Binance lead moves ≥0.1 bps against it
  over 0.5s (PM 5m price moves ~4.4c per bps of BTC — sub-bps drift is the
  entire risk).
- **Fair-value skew**: `edge = Φ(lead/σ(tl)) − mid`, quote UP only while
  edge ≥ −0.08, DOWN only while edge ≤ +0.08. σ(tl) calibrated in
  `fairval.py` (7.75–8.50 bps over the open window).
  The model does NOT beat the book at predicting outcomes (logloss 0.667 vs
  0.648) but (edge) predicts the **mid's own drift** — corr +0.054/+0.084/
  +0.118 at 1s/3s/10s, monotone across every bucket. That is what a maker
  needs: which side is about to be run over.
- Max one order per token per bar; hold to resolution; **merge paired
  inventory** back to $1 via CtfCollateralAdapter to recycle capital.

## 7. Results (19 days, size 50/side unless noted)

btc alone, decomposed per day:

| component | mean/day | t | positive days |
|---|---|---|---|
| **pairs + rebates** | **+$48.55** | **+7.11** | **19/19** |
| directional residual | −$4.52 | −0.08 | 9/19 |
| net | +$44.03 | +0.82 | 12/19 |

btc+eth+sol portfolio:

| | size 25 | size 50 |
|---|---|---|
| pair + rebate engine | +$42.99/day, t=+8.60, **19/19** | +$73.49/day, t=+8.72, **19/19** |
| residual | +$23.38/day, t=+0.54 | +$51.48/day, t=+0.74 |
| net | +$66.38/day | +$124.97/day |
| daily std / max DD | $192 / −$599 | $297 / −$954 |

Per coin (size 50, 19d): btc +0.25 c/sh, eth +0.68, sol +0.89, doge +0.86,
bnb +0.20, **xrp −2.26 (t=−2.06) — EXCLUDE xrp**. Alts pair only 13–44% vs
btc's 73%, so alt numbers are dominated by residual luck; btc is the capacity
(≈85% of all first-minute flow).

**Time split (btc):** first 9 days +$44.94/day, last 10 days +$43.21/day.
⚠️ but a single day (08-11) contributed +$718 of the +$836 net total — that
was **residual luck** (+$708 of it was residual). The *pair* component is what
survives every split: positive on all 19 days, t=+7…+8.7.

### Latency — the gating risk
| reaction (full quote-update cycle) | net c/sh |
|---|---|
| 100ms (1 snapshot — the data floor) | **+0.25** |
| 200ms | −0.43 |
| 400ms | −0.92 |
| 800ms | −2.08 |

At 400ms even the **pair** component collapses (+$922 → −$74): we get filled by
the aggressor on both legs and the two fills stop summing below par. Asymmetric
test: place-latency matters more than cancel-latency (place=0.4/cancel=0.1 →
−0.55; place=0.1/cancel=0.4 → −0.32). **Requirement: ≲100–150ms place+cancel.**

## 8. Economics / what is load-bearing

At size 50 btc: rebate income ≈ **$69/day**, net +$42.61/day ⇒ **without the
maker rebate the strategy is −$26/day. The rebate IS the strategy.**
Verified at the venue (two independent confirmations, per ledger #12/#18):
`feeSchedule={rate:0.07, takerOnly:true, rebateRate:0.2}`, `feesEnabled=true`,
`makerRebatesFeeShareBps=10000`, `feeType=crypto_fees_v2` ⇒ maker rebate
= 0.2 × 0.07 × p(1−p) = 0.35 c/sh at p=0.5. Takers pay, makers do not.
Liquidity-rewards ($10k/day btc 5m pool) are **NOT counted** — the config
attaches ~50s after open, so the first-minute window earns none of it, and the
program ends Aug 31 anyway.

## 8b. Execution feasibility (checked against the repo, 08-19)

- **GTC post-only exists**: `engine/clob.py` →
  `post_order(signed, OrderType.GTC, post_only=True)` — the exchange REJECTS a
  crossing order instead of filling it. This is the maker path and it also
  protects against the stale-place pathology (a quote priced off a stale book
  landing above the new touch).
- **Signing is the constraint, not the network**: `sign_buy_order` is CPU-bound
  ~100–300ms EIP-712 and each signed order is **single-use**. That alone blows
  the ≤150ms budget ⇒ orders MUST be presigned off the critical path.
- **Re-pin budget is comfortable**: the strategy needs only **8.1 placements
  per bar per coin** (measured, `repincost.py`). Re-pinning IS essential
  (repin=False → −1.52 c/sh vs +0.25), but 8 orders/bar means the whole
  .44–.56 band (13 prices × 2 tokens = 26 signatures, ~5s CPU) can be
  presigned during the previous bar's idle 4 minutes.
- Critical path per re-pin is therefore bare POST + cancel ≈ 60–120ms —
  plausible from Helsinki to a Frankfurt-ish CLOB, but UNMEASURED.
  `winner-vacuum/tools/latprobe.py` measures it (5-share post-only bids at
  0.02, cancelled immediately, aborts on any fill).

## 9. Open items before any deploy
1. **Live latency measurement** — the whole result hinges on ≲150ms. Measure
   the real place/cancel round trip from a Helsinki pod before committing.
2. **Fill-rate reality check** (ledger #11 — doc-era fill rates never
   transfer). Sim fills ~71 of a possible 100 shares/bar ≈ 5% of the in-band
   flow; that is the number a pilot must confirm.
3. **Capital/drawdown**: max DD −$599 (size 25) exceeds the ~$95 wallet.
   Start at the venue minimum (`orderMinSize=5`) on btc only, with a sticky
   per-UTC-day halt, and scale only after the live fill rate is measured.
4. Merge-on-pair to recycle capital within the bar (CtfCollateralAdapter).
5. Residual is zero-mean but ±$190/day at size 25 — it cannot be hedged
   (§5), so it must be *sized*, not fought.

## 10. ⛔ THE GATE FAILED — measured venue latency kills it (2026-08-19)

Measured from the LIVE Helsinki vacmaker pods' own event logs (no probe orders
needed — the fleet has been logging this all along):

| metric (btc-vacmaker, /app/logs/logs-training-events.jsonl*) | median | p90 | p99 |
|---|---|---|---|
| `PF_TE_PRESIGN.ms` — EIP-712 signing alone | **13** | 22 | 37 |
| `PF_TE_MAKER_REST.ms` — sign + GTC POST round trip | **190** | 239 | 610 |
| `PF_TE_WHALE_ORDER.ms` — taker FAK round trip | 260 | 408 | 707 |
| `PF_TE_EVAL.pm_msg_age` — book feed staleness | **0.0** | 0.0 | 2.2 |

Three conclusions, all against the strategy:

1. **Signing is NOT the bottleneck — 13ms, not the 100–300ms the
   `sign_buy_order` docstring claims (stale docstring, corrected here).**
   Presigning the band saves ~13 of 190ms. The planned presign pool
   (map keyed by slug, background signer thread, replenish-on-post) would
   have been correct engineering aimed at the wrong 7% of the problem.
2. **The 190ms is VENUE-SIDE, not ours.** Helsinki→Frankfurt network RTT is
   ~25–30ms, so ~160ms is Polymarket's own order processing. More CPU, a
   dedicated node, or co-location cannot reduce it — and Germany/US are
   403-blocked anyway, so we cannot move closer even in principle.
3. **Re-tuned at the real latency, nothing survives** (`realistic.py`, btc,
   19d, full re-sweep of band × fv-gate at delay 0.2/0.3):

| delay | best config | c/sh | $/day |
|---|---|---|---|
| 0.2s | b .40–.60 fv .08 | −0.395 | −$87 |
| 0.2s | b .44–.56 fv .03 | −0.414 | −$64 |
| 0.3s | b .40–.60 fv .08 | −0.618 | −$137 |

The pair component alone still survives at 0.2s in some configs (+$1,652…
+$2,606 over 19d) but the resting leg's pickoff residual (−$2,868…−$5,364)
swamps it. That is the whole failure: at 190ms our quote is stale for ~2
snapshots of a market whose fair value moves ~4.4c per bps of BTC.

**Do not deploy. Do not build the presign pool.** The gate was worth running
before writing the bot: it cost one log query and saved the build plus live
capital.

### Unresolved (the one thing that could reopen this)
The field's at-touch makers earn **+0.57 c/sh gross** in this exact window/band
(§5), while our simulated at-touch quoting earns ≈−0.5 gross at the same speed.
Since the 190ms venue floor applies to them too, either (a) they do not re-pin
at all and accept the pickoff for the rebate, (b) their size/queue treatment
differs, or (c) our fill model over-selects toxic prints. Resolving this is the
only route back — and it is a measurement question, not a tuning one.

### Adjacent, untested, latency-tolerant
The pair+rebate engine is duration-agnostic, but the latency REQUIREMENT scales
with bar length: on 15m the fair value moves ~3× slower per unit time, so a
190ms cycle is proportionally ~3× less harmful. The 15m in-band verdict in
[strat-rewfarm](strat-rewfarm.md) (btc −$205/d) tested the REWFARM design
(all-bar, in-band, 50sh) — NOT this one (first-fifth-of-bar, coin-flip band,
pair engine, fv gate). Out of scope this session (user: 5m only), but it is the
natural next probe if the 5m route stays shut.

## 11. REOPENED — the queue-imbalance gate (2026-08-19, same session)

§10 closed the strategy on latency. Investigating the §10 "unresolved" item
(field at-touch +0.57 c/sh gross vs our sim ≈−0.5 at the same speed) reopened
it. Two hypotheses tested, one refuted, one confirmed.

### 11a. REFUTED: "patience substitutes for speed"
Hypothesis: re-pinning resets us to the back of the queue every time (half-life
1.3–2.3s), so we only ever fill on sweeps; an order left alone ages to the
front. `patient.py`: place once, never re-pin.
**Result −3.44 c/sh vs −0.47 for re-pinning — 7× WORSE.** The mechanism check
passed (it IS latency-insensitive: d0.2 −3.44 vs d0.4 −3.46, identical), but a
fixed resting order is a free option to the market. Notably patience made the
PAIR component 3–5× BETTER (+$2,553 vs +$506) while the residual went
catastrophic (−$12,214) — pairs complete at good prices, singles get run over.

### 11b. Why hedging the residual is STRUCTURALLY impossible (general result)
Completing an unpaired leg cannot beat holding it: the price of the other side
already embeds the information that made our leg bad. Buying a leg at 0.50 whose
true probability is 0.39 has EV −11c; completing when the other side costs 0.60
locks 1−0.50−0.60 = −10c, minus the fee ⇒ −11.7c. Completion converts uncertain
loss into certain loss plus a fee. **That is why every completion variant in §5
lost by roughly the fee, and it generalises to any hedge priced by the same
market.** The residual is irreducible; it can only be avoided, not offset.

### 11c. CONFIRMED: top-of-book queue imbalance predicts the pickoff
`imb = (our-side bid queue − opposite queue) / total`, observable at quote time.
Field at-touch fills in the exact cell (tl 240–297, mpx .44–.56), 354k prints:

| imb bucket | gross c/sh |
|---|---|
| −1.00 … −0.85 (our side thin) | **−1.27** |
| −0.85 … −0.63 | −0.06 |
| −0.63 … −0.20 | +0.47 |
| −0.20 … +0.42 | +0.83 |
| +0.42 … +0.77 | +2.38 |
| +0.77 … +1.00 (our side thick) | **+2.64** |

Monotone over all 6 buckets, 3.9 c/sh spread. Stability (`ofi_stability.py`,
105k HI fills): first half +1.72 vs +1.89 spread, second half +2.80/+2.49 —
stable. HI-bucket daily gross **+2.09, 14/19 days, t=+3.42**.
Also: prints ≥500sh pay the maker **+10.5 c/sh**; our-side depth <46sh is −0.82.

⚠️ The book is MIRRORED (ubs≡das, uas≡dbs) so **imb_UP ≡ −imb_DOWN**: this gate
is inherently ONE-SIDED and gives up most of the pair engine (pair% 57→24-38%).

### 11d. Strategy sim WITH the gate, at the REAL 190ms latency
`imbmm.py`/`imbfull.py`, 6 coins, 19 days, size 50, delay 0.2:

| config | c/sh | $/day | t | pos days | maxDD | pair$ | resid$ |
|---|---|---|---|---|---|---|---|
| no gate (control) | −0.193 | −$65 | −0.67 | 7/19 | −$1,444 | +$56 | −$121 |
| **imb ≥ 0.2** | **+1.669** | **+$151** | **+3.25** | 15/19 | −$313 | +$18 | +$134 |
| imb ≥ 0.2 RAND | +0.718 | +$65 | +1.51 | 12/19 | −$524 | +$18 | +$48 |
| imb ≥ 0.4 | +1.144 | +$75 | +1.68 | 11/19 | −$463 | +$11 | +$65 |

**The gate is latency-INSENSITIVE** (btc+sol+bnb: d0.2 +$84/day, d0.4 +$110/day)
— it selects moments when the book is stably in our favour, so a 190ms stale
quote stops mattering. That is what makes it viable where §6's design was not.

### 11e. What this is and is NOT — read before deploying
- **The gate's real achievement is removing ADVERSE SELECTION.** Ungated, real
  (−$65) sits far below its RAND twin (~+$50-70) ⇒ ≈−$120/day of adverse
  selection. Gated, real ≥ RAND in EVERY config. What remains is ordinary
  spread capture (we buy the bid at ~0.498) + rebates.
- **It is no longer the reliable pair engine.** Pair income collapses to
  $16-20/day (was $73); **~85% of PnL is now the directional residual**, which
  is also the variance source (daily std ~$200). The t=+8.7 / 19-of-19-days
  property of §7 is GONE.
- **Sample is thin**: the gate cuts fills 6× (57.5k → 9.7k). t=+3.25 on the best
  config, but 1.5–1.9 on its neighbours, and the RAND controls are noisy enough
  (+0.45…+1.09 c/sh across runs) that "+$151/day" cannot be separated from
  "+$65/day" with 19 days.
- **The per-coin field split did NOT transfer**: dropping eth/doge/xrp (where
  the field spread is absent/reversed) made the sim WORSE (+$84 vs +$151/day)
  ⇒ treat that split as noise, not structure.

**Verdict: the first 5m maker configuration that is NOT negative at achievable
latency. Promising, NOT yet deployable.** The high-power evidence (field, 105k
fills, t=+3.42, stable) says the signal is real; the low-power evidence (sim,
9.7k fills) says we can capture it without adverse selection but cannot pin the
magnitude. Next step is a minimum-size live pilot (`orderMinSize=5`, btc only,
sticky daily halt) — it tests exactly what the sim cannot: real fill rates, real
queue behaviour and real rebate credit, at ~$20/day of risk.

## 12. LIVE PILOT — deployed 2026-08-19 21:35 Kyiv (btc only, 5 shares)

**Program moved OUT of winner-vacuum** (user, correctly): openmm is its own
program at `openmm/`, sibling to winner-vacuum, with its own chart, its own
`deploy.sh` and its own Polymarket account. It shares ONLY the commons, by the
same symlink pattern winner-vacuum uses:
`src/{config.py,core,engine} -> every-tick-single/src`, `src/execution -> pm-common`.
Deploy: `cd openmm && ./deploy.sh btc paper|live`.

**Account** (separate from the vacmaker fleet by design, so PnL and maker
rebates are independently measurable and a bug here cannot reach the fleet):
signer `0xD17E…FD0a` / vault `0xd632c1e1…` ($168.47 at start).
Key was ALREADY in the repo — `scout.secret.yaml` / `trading-mcp/k8s/secret.env`
both derive to `0xD17E…`. ⚠️ `crypto.secret.yaml`'s comment "signer is the PK /
owner 0xD17E" is WRONG: that key derives to `0x7BbDaf…`. Verify keys by
DERIVING the address, never by reading a comment.
⚠️ `scout.secret.yaml` has NO `polymarketFunder`; the client does
`funder=POLYMARKET_FUNDER or None`, so anything deployed off it signs against
the wrong maker. `openmm.secret.yaml` sets it explicitly.

### 12a. Two live bugs found in the first 10 minutes
1. **Quote thrashing** (paper, immediately): 49 placements in ~50s, churning
   place→cancel(imb)→place. Cause: live top-of-book sizes update per WS event
   and are far noisier than the 100ms mrec snapshots the sim was calibrated on,
   so `imb` whipsaws across the gate line — and it sits right AT it (measured
   live: up 400 vs 253.6 ⇒ imb=+0.224 vs a 0.2 threshold). At a 190ms round
   trip that is unshippable. Fix: MIN_REST (hold a quote against SOFT gate
   flips) + COOLDOWN (space re-placement). Values MEASURED not guessed
   (`backtest/mm5m/minrest.py`, 6 coins/19d at delay 0.2):
   **1.0/0.5 → +1.946 c/sh t=+3.36** vs 0/0 → +1.669/+3.25 vs 1.5/1.0 → +1.387.
   Anti-thrash slightly HELPS. Result live: 49-per-50s → **9 per bar**.
   (Caveat: the sim's min_rest model saturates — 1.5 and 3.0 give identical
   numbers — so it is approximate above ~1.5s.)
2. **MISSING PAIR-COST CEILING — a guaranteed loss on the very first live
   pair.** 18:35 UTC: filled DOWN@0.56, then UP@0.55 = **1.11 paid for a
   guaranteed $1.00 payout, locked −$0.55 on $5.55**. Each leg was inside its
   OWN band at its own moment; only the SUM is the loss. This is exactly
   poolfarm's PAIR_CEIL, learned there from a 1.29 pair / −$14.50 on
   2026-08-12 — and it was not ported. Fixed: once one leg fills at p the
   opposite leg is capped at `PAIR_CEIL − p` (0.985). **Lesson: when writing a
   new bot on this venue, port poolfarm's safety mechanisms as a CHECKLIST;
   they are all scar tissue.** Note the consequence — with the ceiling, a
   0.56 fill blocks the other leg below our 0.44 band floor, so the bot stays
   one-sided by construction, matching the sim's 24-38% pair rate.

Also confirmed live: the **fv gate works** (cancelled an up quote at 0.53,
reason=fv), post-only orders are accepted (0 rejects), and fills are real —
wallet moved $168.47 → $162.92 = exactly 5×0.56 + 5×0.55.

### 12b. What the pilot must answer (it is NOT a profit expectation)
Expected PnL ≈ 0 ± noise at 5 shares. Watch, in order of importance:
1. **PF_OM_REBATES** — does the maker rebate actually credit? Modelled at
   0.35 c/sh at p=0.5. **If this stays ~0 while we fill as maker, every maker
   strategy on this venue is dead**, and that is the single most valuable
   thing this run can tell us.
2. **Fill rate** vs the sim's ~5%-of-in-band-flow assumption (ledger #11:
   doc-era fill rates never transfer).
3. **Pair rate and pair cost** now that the ceiling is in.
⚠️ Restarts wipe in-memory inventory, so day_pnl misses pre-restart positions
(the −$0.55 pair above is not booked). WALLET is truth, not bot counters.

### 12c. BUG 3 — a FAILED cancel is not a no-op (live 18:45, −$0.05)
```
18:45:09 QUOTE  role=down px=0.47 oid=0xcae23792…
18:45:10 CANCEL role=down px=0.47 reason=imb ok=False   ← already FILLED
18:45:12 QUOTE  role=up   px=0.54 → FILL                 ← pair 1.01
```
`_cancel` popped the quote from tracking **regardless of the cancel result**, so
the bot never learned about the down@0.47 fill. The pair ceiling then had no
record of that leg and let up@0.54 through — a 1.01 pair, locked −$0.05. The
ceiling itself was working (at 18:45:23 it correctly allowed only down@0.44,
i.e. 0.985−0.54); it was quoting against a PHANTOM book.

**Rule: on this venue a cancel that returns False almost always means the order
FILLED in the race.** Never discard an order on a failed cancel — reconcile it:
fetch the status, book any `size_matched` as a fill, and if it is still live
keep tracking it (`PF_OM_CANCEL_RETRY`). Both fill paths now go through one
`_book_fill()` so inventory, bar_filled and bar_cost can never diverge.
This is the local-state half of the gap behind the standing rule "no mid-bar
pod restarts until on-chain reconcile exists" — that reconcile still does not
exist; WALLET remains the only truth.

### 12d. First-hour ledger (all reconciled to the cent against the wallet)
start $168.47 → $162.87 at 21:49 Kyiv. Realized **−$0.60, 100% of it the two
pair bugs** (−$0.55 missing ceiling, −$0.05 phantom inventory), not strategy.
Also measured: **post-only reject rate ~29%** (2 of 7 placements) — our bid is
stale by the 190ms flight and would cross, so the venue refuses it. The sim
modelled NO rejections, so the real fill rate will run below simulated; this is
exactly the kind of thing only a live run reveals. `rebates/current` still
returns None — expected this early (daily, $1 min), and it is THE number to
watch.

### 12e. ⚠️ PROVISIONAL — our real latency may be HALF what §10 assumed
openmm now times its own round trips (`PF_OM_QUOTE.ms` / `PF_OM_CANCEL.ms`).
First window, 2026-08-19 19:15 UTC:

| | median | p90 | n |
|---|---|---|---|
| place (sign+POST, post-only GTC) | **91ms** | 334 | 4 |
| cancel | **70ms** | 101 | 3 |

§10's entire "dead on latency" verdict rests on **190ms**, taken from the
vacmaker fleet's `PF_TE_MAKER_REST.ms` (n=117). openmm measures ~half that on
its own orders, and cancels are faster still. This matters because the sim's
gradient is steepest exactly there: ~100ms = +0.25 c/sh for even the PLAIN
design, vs −0.43 at 200ms. If ~90ms holds, §10 was calibrated on the wrong
number and the imbalance gate is doing less of the work than §11 credits.

**NOT revised yet — n=4/n=3, and p90 place is 334ms.** Candidate explanations
for the gap: openmm may sit on a less contended node (6 vacmakers share
finland-worker2, all CPU request 50m / limit 2), venue load differs by hour, or
it is small-sample luck. Let it accumulate over a full day before touching the
§10 conclusion. Whichever way it lands, the lesson is the same: **latency is a
property of a specific bot on a specific pod, not of "the venue" — measure the
bot you are actually shipping.**

Also confirmed this window: MIN_REST works (`rest=1.13–1.17` before soft
cancels) and all 3 cancels returned ok=True, so the earlier "50% lose the race"
(2 of 4) was a small-sample artifact of one busy window, not structural.

### 12f. The 50% "cancel race" is a FILL-DETECTION lag, not a latency race
Corrected 2026-08-19 19:20 (n=22, not the n=4 that made §12e call it an
artifact — it IS ~50%: 11 ok=False of 22). But the cause is not cancel latency:
cancel round trip is only **71ms median**. `_check_fills` polled at **1 Hz**, so
a fill sat undetected for up to a second — and MIN_REST holds a quote exactly
that long. `ok=False` therefore mostly means *"we already filled and had not
noticed"*, and the pair ceiling was reading a book up to 1s stale. That is the
same staleness that let the 1.01 pair through at 18:45.

Two fixes: (a) `FILL_POLL` 1.0s → 0.35s; (b) **the ceiling now also caps against
a LIVE quote on the opposite side** — it may fill at any instant, so treat it as
already filled. (b) costs nothing but a few skipped quotes, and a bad pair is a
GUARANTEED loss, so the asymmetry is worth it.

Confirmed latency at n=23/22: **place 91ms median (p90 210), cancel 71ms
(p90 87)** — about HALF the 190ms §10 was built on, and now a solid sample.
§10's verdict is calibrated on the wrong number; revisit it once a full day of
openmm's own timings exists.

### 12g. ⛔ INCIDENT — a mid-bar restart disarmed EVERY safety cap
2026-08-19 19:22:59 UTC. Bar 19:20–19:25 took **55 shares / $28.10** against a
designed cap of 10 shares / ~$5. Cause: the pod was redeployed MID-BAR, and
`bar_filled`, `inv` and `day_pnl` are all in-memory — they ARE, respectively,
the per-bar cap, the 20-share inventory cap and the $10 daily-loss halt. The
restart re-armed all three from zero, so the bot re-entered a bar it had
already filled. Five restarts in one session ⇒ all three caps disabled five
times. **This is exactly the standing rule "no mid-bar pod restarts (in-memory
inventory → re-buys) until on-chain reconcile exists" — written down, and
broken five times in one session.**

Damage was small only by luck: 50 of the 55 shares were matched pairs, so worst
case was ≈−$3 rather than ≈−$28. Net worth ended +$1.48 (see below).

**Fixes shipped:**
1. **Sit out the startup bar** — `_start_ws` is recorded on the first tick and
   the bot refuses to quote in that bar (`PF_OM_SITOUT`). Mid-bar state is
   unknowable; do not guess it. This makes restarts safe at any time.
2. **Crash-safe halt state** — `day_pnl` + `halt_day` persist to
   `/app/logs/openmm_state.json` (the PVC) and reload on boot, so the daily
   loss halt survives restarts. Without this the halt is unenforceable and a
   bad day can restart its way past the limit indefinitely.
Still missing: true on-chain inventory reconcile at boot (the standing gap).

### 12h. ⚠️ Reading net worth: /positions LIES, use /value
Mid-incident I reported "we are down $28.50 real cash" — WRONG. I read
`data-api /positions`, whose 100-row limit was saturated by ancient worthless
rows on this vault (sz=248 @ 2c, value 0), so our actual positions never
appeared and I concluded the cash drop was realised loss. `/value` is the
correct read: it showed $28.68 of open positions.
**NET WORTH = free pUSD + /value, always** (this is the standing accounting
rule, and I broke it under time pressure). True position at 19:26:
$139.97 cash + $29.98 positions = **$169.95 vs $168.47 start = +$1.48**.

### 12i. BUG 5 — a PARTIAL fill orphaned the resting remainder
2026-08-19 19:50: a 5-share down quote filled **0.78 shares**. `_check_fills`
popped the order from tracking on any `matched > 0` — but 4.2 shares were still
RESTING at the venue. Consequences, all the same class as §12c: the remainder
could fill unseen (phantom inventory), it would never be cancelled, and
`bar_filled` only counted 0.78 so the per-bar cap thought it had room. It fired
immediately — bar 19:50 took down 0.78 + down 5.0 = **5.78 shares on a 5-share
side**.

Fix: `Quote.booked` tracks what we have already accounted for (the venue's
`size_matched` is CUMULATIVE, so re-polling a partially filled order would
double-book), we book only the NEW shares, and the order stays tracked until
`matched >= size`. Applied to both fill paths (poll and cancel-race).

Verified after: `get_open_orders()` = 0, so no orphans survived — PM culls
resting orders at market close and our quotes only live ~57s inside a bar.
**Open hygiene item (not shipped):** a startup `cancel_market_orders` sweep
would make orphans impossible rather than merely unlikely.

### 12j. Day-1 bug tally — the pattern is the lesson
Five bugs in ~75 minutes of live trading, and **four are the same shape**:
local state diverging from venue truth.
1. pair ceiling missing (poolfarm had it; not ported)
2. failed cancel discarded a filled order → phantom inventory
3. fill detection at 1 Hz → ceiling quoted against a stale book
4. mid-bar restart wiped bar_filled/inv/day_pnl → every cap re-armed
5. partial fill orphaned the resting remainder → cap and ceiling both blind

**Rule for any future venue bot: the ONLY authority on our position is the
venue. Every local counter is a cache, and every cache needs an invalidation
story — on restart, on partial fill, on failed cancel.** Sim work cannot find
any of these; they are all reconciliation bugs, and only live trading surfaces
them. That is the pilot earning its keep — five real defects for ~$1 of PnL.

## 13. IMPROVEMENT SEARCH (2026-08-19 late) — 2 rejected, 2 shipped

Scripts: `backtest/mm5m/{skewmm,best,pairfirst}.py`. All 6 coins, 19 days.

### 13a. ⭐ SIM FIDELITY BUG — no sim ever modelled the PAIR CEILING
The live bot enforces it (§12a) but every sim before this let pairs sum > 1.
Adding it improves EVERY config, mechanically (it deletes guaranteed-losing
pairs — not a noise effect):

| config | no ceiling | + ceiling |
|---|---|---|
| gate 0.2, d0.2 | +0.723 | **+1.073** |
| skew 1t | +0.239 | +0.481 |
| skew 2t | +0.421 | +0.744 |
| skew 3t | +0.500 | +0.918 |

⇒ **all pre-§13 sim numbers UNDERSTATE the strategy.**

### 13b. ⛔ REJECTED: imbalance as a price SKEW instead of a hard gate
Motivation: the gate is one-sided by construction (imb_UP ≡ −imb_DOWN) and
that is what destroyed the pair engine. Quote BOTH sides, favoured at the
touch, unfavoured `skew` ticks deeper — keeps pairs completable AND buys the
bad leg cheaper (lower pair sums). Pair rate does recover (25% → 55%), but
per-share is worse: **skew3+ceil +0.918 / t=1.79 vs gate+ceil +1.277 / t=2.40.**

### 13c. ⛔ REJECTED: go back to the pure PAIR engine (+ ceiling)
The pair engine was the only ever-robust component (t=+8.7, 19/19 days), so it
deserved a retest with the ceiling. It is **heavily adversely selected**:

| | real | RAND | selection |
|---|---|---|---|
| PAIR+ceil d0.1 | +0.174 | +1.016 | **−0.84** |
| PAIR+ceil d0.2 | −0.313 | +1.084 | **−1.40** |
| GATE+ceil d0.2 | +1.073 | +1.210 | ≈ 0 |

Huge pair income (+$3,152) entirely eaten by the residual (−$2,340).

### 13d. ⭐ WHAT THE GATE ACTUALLY DOES — correcting §11
The imbalance gate does **not** generate alpha. Across runs the real-vs-RAND
sign FLIPS (real +1.669 vs RAND +0.718 in one run; real +1.073 vs RAND +1.210
in another) — at 19 days the signal's alpha is **not resolvable from noise**.
What the gate reliably does is make our fills **UNBIASED with respect to
outcome** (real ≈ RAND), where the ungated engine is adversely selected by
0.84–1.40 c/sh. The remaining PnL is therefore STRUCTURAL: buying at ~0.496
when fair is ~0.50, pairs guaranteed below par, plus rebates. That is ordinary
market-making income, not a predictive edge — **stop describing it as one.**

### 13e. ✅ SHIPPED: loop interval 0.25s → 0.10s
Effective reaction = LOOP + network. Measured network is ~91ms (§12e), so a
0.25s loop made reaction ~0.34s when the sim gains **+0.20 c/sh** going
0.2s → 0.1s (GATE+ceil +1.073 → **+1.277 c/sh, $152/day, t=+2.40**). The tick
is a few dict lookups and fill polling is separate, so this is free.

**Best known config = what is already deployed** (gate 0.2 + ceiling + fv +
pull + anti-thrash), now with LOOP=0.10. Ready to restart; not restarted —
that is a live-money call.

### 13f. BUG 6 — my own §12c fix caused an infinite re-track FREEZE
2026-08-19 22:25. `_cancel` re-tracked any order whose status was not literally
`cancelled`. An order reported `status=matched` (terminal, already booked) was
therefore put BACK into `quotes[role]` — which (a) blocked new quotes on that
side, (b) was re-polled forever, and (c) on window-close the cancel failed
again and re-added it. **Infinite loop**: 227 `PF_OM_CANCEL_RETRY` in ~90s,
hammering the venue every tick (worse after LOOP 0.25→0.10), and it killed the
log monitor by output rate.

Fix: `_TERMINAL = (matched, filled, cancelled, canceled, expired, rejected,
invalid)` — a failed cancel on any of these DROPS the order; only genuinely
live statuses are re-tracked.

Two operational lessons:
1. **The stuck pod would not terminate** (14 min in `Terminating`, still
   spamming) and blocked the rollout — needed
   `kubectl delete pod --grace-period=0 --force`. A tight retry loop makes a
   pod undeployable; always check the rollout actually completed.
2. **A monitor filter must be duplicate-throttled.** One repeating line took
   the watch offline exactly when it mattered. The monitor now suppresses
   identical messages within 300s.

**Bug 6 of 6, and the 3rd caused by a FIX rather than the original code**
(§12c fix → this; §12i partial-fill handling → introduced by the same reconcile
work). Reconciliation logic is where this bot's bugs live; every change there
needs the terminal-state question asked explicitly: *what are ALL the states
the venue can report, and what do I do in each?*
