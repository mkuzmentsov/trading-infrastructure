# btc 5m opportunity scan on the FRESH mrec build — 2026-09-07

**Scope:** btc only (user: *"only btc for now"*), 5m up/down.
**Data:** purpose-built btc parquet, **09-01 20:00 → 09-06 20:50 UTC, 1,447 resolved bars,
1,883,569 prints** — +11 hours / +16% bars over anything analysed before.
**Working dir:** `scratchpad/scan/` (`t1_*.py`, `t2_mint.py`, `t2b.py`, `t3.py`, `t3b.py`,
`t4.py`, `t4b.py`, `t5.py`); harness = `reb/mm.py` + `pess2/qdecay.py` re-pointed, which
**reproduce the published rebate-farm headline on the fresh data** (static −0.238 ± 0.632 vs
published −0.326 ± 0.663; drain HL 1.8 −0.451 ± 0.599 vs −0.594 ± 0.624).

**One-line verdict: nothing new is tradeable. The only thing that moves is the ask floor.**

---

## 1. ⛔ GENUINE PAIR ARBITRAGE — DOES NOT EXIST. Bounded by an identity, 0 occurrences.

The user's "two-sided, taker other leg for the same dollar amount" in its strongest form:
buy UP and DOWN simultaneously for less than $1 and redeem the pair.

**Re-verified bit-exactly on the fresh build, on 1,991,479 event-exact `(ws,mts)` pairs of the
two token books:**

| identity | result |
|---|---|
| `ua ≡ 1 − db` | **100.0000%** exact, max dev 0.0 (n=1,966,903) |
| `ub ≡ 1 − da` | **100.0000%** exact (n=1,966,637) |
| UP-ask SIZE ≡ DOWN-bid SIZE | **99.9997%** bit-identical |

⇒ `ua + da ≡ 1 + spread` **algebraically**. Measured over 1,942,072 event-exact states:

| both-legs-taker pair | value |
|---|---|
| gross pair cost `ua+da` | min **1.0010** · median 1.0100 · mean 1.0156 |
| fee-inclusive pair cost | min **1.00121** · median 1.0402 · **mean 1.0395** |
| states below $1.00 gross | **0** |
| states below $1.00 fee-inclusive (a real arb) | **0 of 1,942,072** |
| per day (6 days) | cheapest achievable pair cost **1.00121 every single day** |

**A completed taker pair costs $1.0395 for a $1.00 payout — a 3.95 c/pair structural loss.**
Mid-band (bid 0.40-0.60) it is worse: mean **1.0516**, and the fee-inclusive break-even sum is
**0.9650**, which the book is never within 8.7 c of.

The brief's closed item #1 also reproduces exactly: maker UP bid + taker DOWN ask =
**1.000000** in 100% of mid-band states ⇒ **−1.378 c/share** (brief said −1.40). ✔

### 1b. ⚠️ THE TRAP — and a new, generalisable diagnostic (→ ledger #32)
The tape version of this scan **reads +$38,585 / 6 days** if you do the obvious thing: for each
print proving one leg takeable, take the *cheapest* opposite-leg print inside a 0.4s window. It is
pure hindsight (bug #13's "min over window"): the top hit is a bar where the UP price moved
**0.22 → 0.86 in 400 ms** and the scan buys UP before the move and DOWN after it.

Replacing "min in window" with the causal "**first** opposite-leg print at ≥ t+LAT" does **not**
fix it — it still reads +$18,911, and the tell is unmissable:

| LAT | 0.00 | 0.05 | 0.20 |
|---|---|---|---|
| "profit" ($/6d) | 18,911 | 23,177 | **39,349** |

**A real arbitrage shrinks with latency. This one grows monotonically.** It was never measuring
co-availability, it was measuring path dispersion: *a print proves the book WAS at that price at
or before the print — never that it is there now, and you cannot retroactively have been the
taker.* Any pair/arb statistic must be read off the **book at one instant**, not off two prints.

---

## 2. ⛔ MINT/MERGE AS THE COMPLETING LEG — the mint contributes exactly $0, and the maker exit is
   the most adversely-selected instrument in this book.

Construction tested (the brief's): rest a maker bid on UP at the touch; on fill, **mint a pair for
$1 via the collateral adapter and sell the unwanted side as a maker**, replacing the 1.75 c taker
completing leg with a maker exit. btc, q 0.40-0.60, tl 40-270, touch join, queue drain HL 1.8,
LAT 0.20, tape-size capped (bug #28). **5,006 leg-1 maker fills / 173,339 shares.**

### 2a. The arithmetic: minting is a NO-OP
Mint $1 → 1 UP + 1 DOWN; sell the extra UP at `a`; you end holding a pair that redeems $1.
Cash = `−q −1 +a +1` = **`a − q`** — identical to just selling the UP you already own. And a
resting *sell of UP at a* and a resting *buy of DOWN at 1−a* are **the same order in the same
queue** (UP-ask size ≡ DOWN-bid size, 99.9997% bit-identical, §1). So the mint route is not a new
construction: **it is the two-sided resting maker, already measured and dead.** Gas is irrelevant
either way — the repo's own MINTSALVAGE measurement is ~$0.01/mint = **0.02 c/share on a 50-share
clip**, against a −3 c/share mechanism.

### 2b. Measured anyway, on the mid-bar 0.50 book (the cell prior mintsalvage never touched)

| completing route | net c/share (bar-clustered) | days+ |
|---|---|---|
| **C — do nothing**, carry the naked leg to settlement | **+0.155 ± 2.033** | 3/6 |
| A — taker-buy the DOWN ask | −0.145 ± 1.611 | 2/6 |
| D — taker-sell the UP at the bid (control) | +0.355 ± 1.521 | 4/6 |
| **B1 — MINT-pair: maker ask quoted at the placement touch** | **−3.250 ± 0.337** | **0/6** |
| B2 — mint + maker ask re-priced after the fill | −3.620 ± 0.293 | 0/6 |
| Bf — same, floored at cost + 1 tick | −3.918 ± 0.371 | 0/6 |

Paired against "do nothing" on the same fills: **B − C = −3.79 ± 1.91 c/share (0/6 days)**;
A − C = −0.32 ± 0.56; D − C = +0.18 ± 0.64.

### 2c. ⭐⭐ THE MECHANISM — why a maker exit cannot work on a bar that resolves inside its life
The mint-pair's maker ask is **not** a bad price. It **captures a real +1.229 c/share spread**,
and it fills on **89.8% of shares**. The other **10.2% of shares are worth −49.28 c/share** — i.e.
essentially every share whose exit ask never fills is a **total loss**.

> A resting ask fails to fill *precisely when* the token is collapsing to zero, which on a 5m
> binary is the same event as losing the whole stake. The maker exit therefore converts a
> symmetric ±50 c position into **"win 1.2 c / lose 49 c"** — it sells all the winners at the
> spread and keeps 100% of the losers. It is a disposition-effect machine, enforced by the book.

This is the mid-bar 0.50 analogue of the 0.99 queue-position death that killed mintsalvage, and it
is a **stronger** result: mintsalvage failed on *fill rate*; this fails at a **90% fill rate**.

### 2d. Bonus measurement, worth carrying: the completing leg is 1.63 c more expensive than the identity
Maker UP bid + taker DOWN ask is exactly 1.000 **at the same instant**. At the instant you can
actually act (fill time + 0.20 s LAT) the sum is **1.01633** — the touch has already fallen
**1.63 c** (bid) / 0.47 c (ask) in those 200 ms. That gap *is* the adverse selection, measured
directly on the completing leg rather than inferred from a markout.

---

## 3. THE VACMAKER'S OWN LANE, re-cut on the fresh btc bars

House fill model (§72): **0.4 s window, 0¢ price improvement, top-3 ladder walk, CLIP $24 /
LADDER $48, tape-SIZE capped (bug #28)**, live policy (tl 3-20, threshold `0.10+0.035·max(0,tl−14)`,
cov ≥0.5, ask 0.55-0.99, first-clip skip 0.90-0.98, ladder floor 0.94, 8 s gap).
**101 clips over 6 days (16.8/day — matches the fleet's 15.2 btc clips/day).**
⚠️ btc is ~1/7 of the fleet; **do not compare these dollars to fleet day closes.**

**Losing clips/day first (the fill-model-independent metric):**

| arm | clips | **losing clips/day** | $/day | worst day | days+ |
|---|---|---|---|---|---|
| baseline MIN_ASK 0.55 | 101 | **0.83** | −0.78 | −35.74 | 5/6 |
| + veto vB (`dB20≤−0.03 & |est|<5`) | 98 | 0.50 | 0.00 | −32.96 | 5/6 |
| + veto vR (`rB10≤−0.25`) | 99 | 0.50 | +2.45 | −32.96 | 5/6 |
| MIN_ASK 0.75 | 96 | 0.17 | +4.96 | −6.71 | 5/6 |
| **MIN_ASK 0.90** | 92 | **0.00** | **+5.06** | **+0.14** | **6/6** |
| MIN_ASK 0.98 | 88 | 0.00 | +4.01 | +0.14 | 6/6 |

### 3a. ⚠️ ON btc, THE BID-DROP VETO DOES NOT DELIVER ITS TAIL FILTER
The whole btc baseline result is **5 losing clips**. vB/vR remove 2 of them and **miss the one
that makes the worst day** (−$24.66, ask 0.61, tl 15, 09-04 13:00). Worst day goes −$35.74 →
−$32.96 — a 8% improvement, against the fleet-wide claim of "−$34…−$76 → positive". The handoff
already flagged btc as the smallest beneficiary (+$1.11/day, 0.3 blocked losses/day); on the fresh
bars it is **not a tail filter on btc at all**. Nothing here argues against the fleet-wide finding
— it argues against piloting the veto on btc.

### 3b. The ask floor separates the losses cleanly, and it is the same 5 clips

| ask band | clips | losses | win | breakeven win | ROI% |
|---|---|---|---|---|---|
| .55-.75 | 7 | **4** | 0.429 | 0.641 | **−19.33** |
| .75-.90 | 6 | **1** | 0.833 | 0.892 | −8.25 |
| .90-.98 | 4 | 0 | 1.000 | 0.965 | +3.82 |
| .98-.99 | 84 | 0 | 1.000 | 0.988 | +1.24 |

All 5 losing clips sit in the 13 clips below ask 0.90 (sub-0.90 win **8/13 = 61.5%** vs a
**75.7%** break-even; ≥0.90 is **88/88**). Hypergeometric p = **1.6 × 10⁻⁵**, **5.4 × 10⁻⁴** after
the §72 33-rule family correction. Day-wise the ≥0.90 arm is **6/6 days positive with 0 losing
clips**.

**⚠️ This is NOT independent confirmation of §72-3.** Five of these six days are the same days.
The genuinely new evidence is the fresh 11 hours: **15 clips, 1 loss — at ask 0.60.** Consistent,
but that is n=1. What would falsify: a losing clip at ask ≥ 0.90, or a sub-0.90 clip cohort that
turns positive on the next re-cut.
**Multiple comparisons account for §3:** 3 veto forms × 4 ask floors × 3 size models = 36 cells;
the ask floor is the only axis whose ordering is monotone on all three of $/day, losing clips and
worst day, and it was pre-specified by §72-3, not discovered here.

---

## 4. WHAT THE FRESH 11 HOURS LOOK LIKE (09-06 09:50 → 20:50 UTC vs the prior 109 h)

### 4a. ⭐ The phantom cheap-ask layer is GONE and has stayed gone — quantified per day
Late window (tl 3-20, decisive bars), favourite-side ask, **tape-gated** (bug #23 addendum):

| day | displayed ask % of secs | 0.4 s tape-confirmed % | **cheap (<0.90) displayed %** | **cheap tape-confirmed %** |
|---|---|---|---|---|
| 09-01 | 26.2 | 0.12 | **25.3** | 0.00 |
| 09-02 | 17.1 | 1.83 | **14.8** | 0.20 |
| 09-03 | 19.8 | 2.16 | **16.4** | 0.63 |
| 09-04 | 3.3 | 2.17 | 1.33 | 0.46 |
| 09-05 | 3.8 | 2.72 | 0.78 | 0.08 |
| 09-06 AM | 2.0 | 1.67 | 0.73 | 0.61 |
| **09-06 PM (fresh 11 h)** | **3.4** | **2.22** | **0.89** | **0.16** |

The *displayed* cheap layer collapsed **19×** on 09-04 and has not returned. The **tape-confirmed**
supply is flat at 0.0-0.6% throughout — it was always mostly phantom. ⇒ any panel-derived
availability statistic pooled over 09-01→09-06 **mixes two regimes at a ~10× ratio**; split at
09-04 or tape-gate.

### 4b. Everything else: mildly thinner, mildly tighter, same pool
| | old 109 h | fresh 11 h |
|---|---|---|
| mid-bar spread = 1 c | 94.7% | 97.1% |
| touch depth median (bid / ask) | 168 / 182 sh | 159 / 164 sh |
| taker tape | $267 k/h | **$216 k/h** (−19%) |
| settlement-window winner supply (tl 3-20 BUY tape) | $3,828/h | **$4,536/h** |
| winner shares ≤0.90 / h | 509 | 593 |
| TWAP-60 recon accuracy | 99.16% | 99.31% |
| median \|margin\| | 4.65 bps | **2.77 bps** |

**The vacmaker's pool did not shrink.** The one real difference is that bars are settling
**tighter** (median \|margin\| 4.65 → 2.77 bps) — a harder regime, and the 1 loss in 15 fresh
clips is consistent with it. 145 bars is far too few to call a $/hour rate.

---

## 5. FREE HUNT — follow-the-flow taker at the mid-bar. ⛔ dead, as the fee arithmetic requires.
Motivated by §2d (the touch really does move 1.63 c in 200 ms). Trigger = a bid-consuming print;
action at +0.20 s = taker-buy the falling side's complement at its ask, tape-gated + size-capped,
hold to settlement. btc, tl 40-270, $24 clips.

| arm | n | stake | ROI | days+ |
|---|---|---|---|---|
| trigger ≥ 20 sh | 105,403 | $1.57 M | **−1.67%** | 2/6 |
| trigger ≥ 100 sh | 22,099 | $329 k | **−2.05%** | 2/6 |
| control (fixed 5 s clock) | 15,223 | $175 k | −3.36% | 0/6 |

The trigger beats the no-trigger control by ~1.7 pp — **the information is real** — and is still
comfortably negative, because the realised win rate is short of the price-implied break-even in
**4 of 5 price bands** (.35-.45 −3.3 pp, .55-.65 −1.7 pp, >.65 −1.0 pp, <.35 −0.2 pp; only
.45-.55 is +0.3 pp at the ≥20 threshold and it flips to −1.7 pp at ≥100 = unstable). The 1.63 c
move is smaller than the 1.75 c taker fee that buys access to it. Re-confirms
[[strat-momtaker]] on the fresh tape.

---

## 6. WHAT I DID **NOT** TEST, AND WHERE THIS IS MOST FRAGILE
1. **Cross-market / cross-venue pairs.** Only the btc 5m two-token book. A UP-5m vs the two
   overlapping 15m/1h markets pair is a different (and untested) object.
2. **Sizes above one $24 clip / 50-share quote.** Everything is capped at the live sizes.
3. **The ≥0.90 result rests on 5 losing clips**, 5 of 6 days shared with §72-3. It is a
   *replication*, not an independent test. It is also a **replay**: bug #23 says sub-0.90 asks fill
   ~11% live, so the 13 sub-0.90 clips may be over-represented relative to live behaviour — which
   would make the ask floor matter *less* live than here, not more.
4. **The mint route was tested with a maker exit at the touch only** — not at deeper levels, and
   not with an exit that is cancelled and re-quoted. The −49 c non-fill branch is a property of
   the bar resolving, so I expect no level to escape it, but it is not measured.
5. **`side='BUY'` is assumed to be the aggressor side** throughout (per the mrec v2 README). Every
   §1 identity result is independent of that assumption; §2/§5 are not.
6. **Task 5's per-bar clustered SE is wide** (−19.4 ± 33.1 per bar): the verdict rests on the
   band-wise win-vs-breakeven table and days+, not on the aggregate t.

---

## LEAD VERIFICATION (2026-09-07) — the ask-floor result reproduced, and three reasons not to act on it yet

Re-ran the ask-floor claim independently on the fresh btc build (`scratchpad/verify/vfloor.py`),
house cell + tape-SIZE cap, live gates:

| MIN_ASK | clips | stake | pnl | $/day | ROI | losing clips | worst day | positive days |
|---|---|---|---|---|---|---|---|---|
| **0.55 (live)** | 101 | $2,002 | **−$4.69** | −0.78 | −0.23% | **5** | **−$35.74** | 5/6 |
| 0.75 | 96 | $1,914 | +$29.77 | 4.96 | 1.56% | 1 | −$6.71 | 5/6 |
| 0.85 | 95 | $1,909 | +$22.66 | 3.78 | 1.19% | 1 | −$6.71 | 5/6 |
| **0.90** | 92 | $1,873 | **+$30.39** | **5.06** | **1.62%** | **0** | **+$0.14** | **6/6** |
| 0.95 / 0.98 | 88 | $1,847 | +$24.03 | 4.01 | 1.30% | 0 | +$0.14 | 6/6 |

Band decomposition of the live baseline: **below 0.90 = 13 clips, 5 losses, −$29.05**;
**at/above 0.90 = 88 clips, 0 losses, +$24.36**. The entire btc loss in the window is the
sub-0.90 band, and 0.90 beats 0.95 by $6.36 (the four ladder clips in 0.90-0.95).

### ⚠️ Three reasons this is NOT yet a deploy recommendation
1. **The effect is 5 losing clips.** Everything above is that sample.
2. **It contradicts the fleet-wide result that the cheap band is the PROFIT CENTRE** — §41 measured
   ask 0.75-0.90 at +3.98% ROI and 62% of the reverse-engineered whale's profit came from entries
   below $0.80. This is btc-only, one 6-day window. And §68-3b established that **per-coin replay
   results are anti-correlated with live (r = −0.63 on coin totals)**, which is exactly the kind of
   claim being made here.
3. **Bug #23 cuts against it.** A displayed sub-0.90 ask fills ~**11%** live against a much higher
   rate in any replay, so the live bot is already taking far fewer of these clips than the sim
   does. The floor would therefore matter **less** live, not more — the replay overstates the prize.

**What would settle it:** the live fill ledger, not another replay. Count the live btc clips that
actually filled below 0.90 over the last 3-4 weeks and their realised PnL. That is a read-only
query against the bot's own logs and it is the only evidence that is not subject to (3).

### ⚠️ New negative that changes an earlier recommendation
**The bid-drop veto (vB) and its relative form (vR) are NOT tail filters on btc.** They remove
2 of the 5 losing clips and **miss the −$24.66 clip that creates the worst day** (−$35.74 →
−$32.96, an 8% improvement). §66/§70's pilot guidance should not be applied to btc. This is
consistent with §68-3b: the per-coin ordering in those sections was never reliable evidence.

---

## ⛔⛔ LIVE GROUND TRUTH REFUTES THE ASK-FLOOR RESULT (2026-09-07, lead)

The verification above ended by saying the question could only be settled from the live fill
ledger. It has been. **The replay was backwards.**

Source: `btc-vacmaker` pod `logs-training-events.jsonl` + rotated archives, `PF_TE_LIVE_SETTLE`
rows (read-only `kubectl exec`). **316 settled live btc fills, 2026-08-17 → 09-06** (3 weeks —
5× the replay window). Each row carries the ACTUAL fill price (`avg_px`), cost, payout and outcome.
Fleet total over the window: **+$120.62 on $3,616 staked, ROI 3.34%, win 97.2%.**

### Raising the ask floor destroys profit, monotonically

| floor on actual fill price | fills | losses | pnl | ROI |
|---|---|---|---|---|
| **none (live config)** | 316 | 9 | **+$120.62** | **3.34%** |
| ≥0.55 | 313 | 7 | +$98.56 | 2.74% |
| ≥0.75 | 300 | 5 | +$77.18 | 2.21% |
| ≥0.85 | 288 | 4 | +$58.67 | 1.73% |
| **≥0.90** | 271 | **3** | **+$44.80** | 1.39% |
| ≥0.95 | 244 | 2 | +$36.15 | 1.21% |

**MIN_ASK 0.90 would have cost −$75.82, i.e. 63% of all profit.** It removes 6 losses worth
−$40.75 and forfeits **39 wins worth +$116.57**.

### The cheap band is the PROFIT CENTRE on live fills — §41 confirmed, btc-specifically

| | fills | losses | cost | pnl | ROI |
|---|---|---|---|---|---|
| **below 0.90** | 45 | 6 | $401.37 | **+$75.82** | **+18.89%** |
| 0.90 and up | 271 | 3 | $3,214.72 | +$44.80 | +1.39% |

Mechanism: down there the payoff asymmetry runs the OTHER way. The cheap band wins **86.7%**
against a ~75% break-even at its mean price, and each win pays `(1−p)/p` — so 39 wins averaging
~$3 swamp 6 losses averaging ~$6.80. (Above 0.90 a win pays ~1-2c and a loss costs ~$7.60: that
is the 30:1 regime. Below 0.90 it is roughly 1:2. **They are different businesses and the same
gate cannot serve both.**)

### Why BOTH replays got it backwards — bug #23, in the direction that matters
A displayed sub-0.90 ask fills ~**11%** live (bug #23, n=295) against 22-60% in every replay.
So the live bot's sub-0.90 population is the small subset where the *price improvement was real*;
the replay's sub-0.90 population is dominated by phantom asks that would never have filled. The
sim was not mis-scoring those clips — it was trading a population that does not exist.
**Two independent agents and the lead all reached the opposite conclusion from replay.**

### Standing rule this establishes
> **A per-band gate on a LIVE strategy must be settled from the live fill ledger, never from a
> replay.** `PF_TE_LIVE_SETTLE` carries `avg_px`, `cost`, `payout`, `won` — three weeks of it
> takes one `kubectl exec` and it outranks any amount of offline work on the same question.

⚠️ Note `req_px` is present on only **11 of 316** rows (all 0.99), so the *displayed*-ask
distribution cannot be recovered from this log. Adding `req_px` (and the displayed size) to every
`PF_TE_BET`/`PF_TE_LIVE_SETTLE` row is a one-line recorder change that would make the whole
bug-#23 question directly measurable in future. **Recommended.**
