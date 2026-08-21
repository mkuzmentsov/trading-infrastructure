# MAKER PROGRAM 2026-08-19→21 — complete record of everything tried

Two-day push to build a **maker-oriented, rebate-harvesting, market-neutral**
strategy on Polymarket crypto up/down markets (user brief: *"neutral or even
profitable… primary aim is to gather maker rebates"*). **Outcome: CLOSED
NEGATIVE at 5m, 15m and 1h.** Cost: **−$61** total (5m −$53.78, 1h −$7.2).

**Read [[maker-resting-order-wall]] first** — one measured number explains every
failure below. This file is the exhaustive inventory so nothing gets retried.

---

## 0. THE CENTRAL FINDING

> **A resting bid quoted 1.5c BELOW the mid gets filled 0.47c ABOVE it, and
> 48% of fills execute above the prevailing mid.** (304 1h btc bars,
> `pairceil1h.py`.) Against a **+0.35c** maker rebate ⇒ **−0.47c of adverse
> selection per fill**, before any strategy logic.

Not a defect — it is what a resting order *is*. Nothing happens while the mid
sits still; you fill when the mid **falls to you**, at which point you are no
longer below it. Quoting deeper is *worse* (2.5c ⇒ fills at −1.15c, 59% above
mid): **depth buys a worse selection, not a better price.**

**Corollary that killed every mitigation:** any action priced by the market —
selling the leg, completing it as taker, hedging — costs exactly what the
position is already worth. **Only the ACQUISITION price matters.** Proven in
data: every exit/completion variant returns RAND == real, i.e. pure
transaction cost with zero selection benefit.

---

## 1. METHOD (and the trap that recurred 4×)

Pipeline: **field terrain → queue-aware sim → live**, on the local mrec archive
(100ms full-bar, 07-30→08-17, 7 coins, 4.8 GB).

⚠️ **THE RECURRING TRAP: a field-average cell is NOT the subset you will get.**
Four separate cells looked strongly profitable field-wide and died under a
queue-aware sim:

| cell | field | with queue model |
|---|---|---|
| 5m tail (maker long .85–.96) | +0.90 c/sh | **−0.41** |
| 5m "swept-deep" bucket | +3.44 | **−4.2** (stale-snapshot artifact) |
| 15m underdog (.15–.30) at touch | +2.09 | **+0.17** (RAND +22.46 ⇒ −22.3 adverse) |
| 1h aggregate terrain | — | sim −0.246/bar = live |

Reason (now understood): field averages include makers filled **without** the
mid moving; a resting order is structurally the **opposite** population.

**Validity controls that repeatedly caught errors** — always run all three:
`RAND` (shuffled outcomes) isolates selection from mechanical structure;
`NOQ` (queue ignored) must be BETTER than the queue-aware run; an
unconditional/mid-quoting control must LOSE.

---

## 2. WHAT WAS TRIED — 5m (`openmm/`, own program, own PM account)

Design: two-sided maker, band .44–.56, first 60s of bar, imbalance-gated.
Full detail: [strat-openmm-5m](strat-openmm-5m.md).

### Terrain findings (all prints, maker side, no fill model)
- Aggregate 5m maker is **~breakeven**: −0.010 c/sh net (gross −0.209 + rebate
  +0.199). Zero-sum check: takers net −0.79 c/sh, venue keeps the rest.
- Losses concentrate: mid-bar −0.297, **first minute +0.411**, first 4s −0.405
  (stale pre-open orders swept at rotation), long-the-underdog −0.387.
- Structure: **spread is 1 tick 97.5% of the time** (effective tick 1c despite
  `orderPriceMinTickSize=0.001`); touch queue 130–240 shares; **queue half-life
  1.3–2.3s** (cancellations 2–4× trades); **touch price dwell only 0.4–0.6s**.

### Levers tested
| lever | verdict |
|---|---|
| sell the cheap tail (long .85–.96) | ⛔ −0.41 c/sh with queue (field +0.9) |
| rest BELOW touch to absorb sweeps | ⛔ −4.2 c/sh; the field's "+3.44 swept-deep" is a **stale-snapshot artifact** |
| patient (place once, never re-pin) | ⛔ −3.44 vs −0.47; latency-insensitive but a free option to the market |
| re-pin at touch | ✅ essential (−1.52 → −0.25) but needs ~8 placements/bar |
| taker completion of unpaired legs | ⛔ −$92/day — the pair ceiling only permits completion when the other side is CHEAP ⇒ **cuts winners, keeps losers**; fee peaks at p=0.5 (1.75 c/sh) |
| maker completion (+1 tick) | ⛔ −$9/day; completing leg fills exactly when the market turns |
| quiet-market filter (buy latency tolerance) | ⛔ does not rescue 200–400ms |
| fair-value skew (Φ(lead/σ) − mid) | 🟡 small help; model does NOT beat the book at predicting outcomes (logloss 0.667 vs 0.648) but DOES predict the mid's drift (corr +0.05/+0.08/+0.12 at 1/3/10s) |
| **queue-imbalance gate** | ⭐ the one thing that worked: field spread −1.27 (thin) → +2.64 (thick), monotone over 6 buckets, t=+3.42 on 105k fills; flips sim −$65 → +$151/day AND is latency-insensitive |
| skew instead of gate | ⛔ +0.918 vs +1.277 c/sh |
| pure pair engine + ceiling | ⛔ heavily adversely selected (−0.84…−1.40 vs RAND) |
| volume/size scaling | pair income scales linearly; residual is the variance |

### Latency (the 5m gate)
Sim: 100ms +0.25 c/sh → 200ms −0.43 → 400ms −0.92 → 800ms −2.08.
**Measured live from the vacmaker fleet's own logs**: signing **13ms** (the
`sign_buy_order` docstring claiming 100–300ms is STALE), maker order round
trip **190ms median** — and Helsinki→Frankfurt RTT is only ~25–30ms, so ~160ms
is **venue-side and unfixable** by CPU, co-location or presigning (and DE/US
are 403-blocked anyway). openmm's own orders later measured **91ms place /
71ms cancel** — latency is a property of a specific bot on a specific pod, not
of "the venue".

### Live pilot (btc, 5 shares, ~90 min)
−$53.78. **Six live bugs, four of them the same shape (local state diverging
from venue truth); three were caused by my own fixes:**
1. **pair ceiling missing** (poolfarm had it; not ported) → 1.11 pair = locked −$0.55
2. **failed cancel discarded a filled order** → phantom inventory → 1.01 pair
3. **fill detection at 1 Hz** → ceiling quoting against a stale book
4. **mid-bar restart wiped bar_filled/inv/day_pnl** → all three caps re-armed → 55 shares vs a 10 cap
5. **partial fill orphaned the resting remainder** → cap and ceiling blind
6. **terminal-status re-track freeze** (my §12c fix) → infinite `CANCEL_RETRY`, 227 in 90s, pod undeployable

⇒ **Rule: the only authority on our position is the venue. Every local counter
is a cache and needs an invalidation story — on restart, on partial fill, on
failed cancel.** None of these are findable in simulation.

---

## 3. WHAT WAS TRIED — 15m

Same calibrated harness (`pairsim15.py`, `terrain15.py`, `dog15.py`).
- Aggregate terrain is the **BEST of the three durations**: net **+0.259 c/sh**
  (gross +0.041 — the only duration where gross is positive).
- **But it did not transfer.** Best pair config −$0.160/bar × **96 bars/day =
  −$15/day**, worse in absolute terms than 1h. RAND +0.498 vs real −0.266.
- The underdog cell (.15–.30, +2.09 field, at-touch and NOT an artifact) dies
  under the queue: **+0.17 c/sh, t=+0.12**, RAND +22.46.

---

## 4. WHAT WAS TRIED — 1h (`poolfarm.py`, btc+eth, ~28h live)

Chosen because the 5m killer was the UNPAIRED leg (53% of shares) and pair
completion is mechanical in bar length (5m 63% → 15m 72% → **1h 84%**), plus
latency stops mattering. **Deployed poolfarm.py — battle-tested, live-proven at
1h (+$1/bar, 7/7 pairs) — NOT a new bot.** Result: 0 strategy bugs vs 6.

### ⭐ The sim became CALIBRATED here
`pairceil1h.py` predicts **−$0.246/bar**; live delivered **−$0.238/bar** over 35
resolved bars — **3% agreement, the first time a backtest reproduced live PnL
in this program.** Its verdicts below are therefore trustworthy.

### Live decomposition (35 bars)
`pairs +$7.74 (+3.01 c/pair-share, exactly the 2×EDGE_C prediction)` ·
`residual −$16.08 (−13.98 c/sh on 115 unpaired shares)` · `total −$8.34`.
Need ~2.2 pair-shares to fund each unpaired share; we ran at exactly 2.2:1.

### Levers tested (304 bars)
| lever | verdict |
|---|---|
| PAIR_CEIL 0.985 → 1.00 → 1.02 → 1.05 → 1.10 → OFF | best OFF, **still −$0.103/bar**. Ceiling ON ⇒ pairs +$175 / residual −$250; OFF ⇒ residual ~0 / pairs −$58. **Mutually exclusive by construction.** |
| EDGE_C 0.3c → 2.5c | shallow better; all negative. Reachable maker volume **halves per extra cent** of depth while profit grows only linearly ⇒ optimum ~1.0c, worth just +15% |
| exit naked leg near bar close | ⛔ WORSE (−0.246 → −0.413) |
| cut naked leg 5/15/30/60/180s after fill | ⛔ catastrophic (−$3.07/bar); destroys 70% of pairs; **RAND == real ⇒ pure transaction cost** |
| taker completion (buy missing side, unconditional) | ⛔ residual → **0%** as designed, but −$0.28/bar; **RAND == real** |
| volume scaling (size 10→20→40) | ⛔ loss/share ~constant (−0.53…−0.74c); **doubling volume doubles the loss**; rebate (0.35c) is already counted and is 2.5× too small to close it |
| volatility gate on entry | ⛔ no predictive power (corr −0.056); **87% of bars DO oscillate enough to pair**, and there is **no vol clustering at 1h** (corr −0.061) |
| mint/merge "atomic pair" | ⛔ **NOT a distinct mechanism** — book is **100% mirrored** (34,526 snaps: DOWN bid ≡ 1−UP ask) ⇒ an ask on UP at `a` IS a bid on DOWN at `1−a` |

### 1h market facts (differ from 5m)
Settles on **Binance 1h candles**, not the Chainlink TWAP ⇒ our spot feed is
the exact settlement source. ET name-based slugs. **UMA resolution, 600s
liveness** ⇒ capital locks past the bar. **No funded liquidity-reward pool**
(`rewards/markets` count=0 — the $1M program is 5m/15m/4h); the maker REBATE
does apply. **Only btc and eth are viable**: measured 1h volume btc $16.5k/day,
eth $2.1k, then xrp $695, sol $229, doge $45, bnb $13 with 3–11c spreads —
a pair cannot complete there and an unpaired leg cannot be exited.

### Reconcile loop (added to poolfarm.py) — 3 bugs, all found by TESTING
`reconcile_loop` raises `inv` toward venue truth (monotone ⇒ can only make caps
stricter). **It ran clean with zero errors while protecting nothing, twice.**
1. **Inert query** — `/positions` caps at 100 rows and this vault is saturated
   by 100+ ancient worthless rows (sz=248 @ 2c) ⇒ live rows never appeared
   (`100 rows, 0 matching`). Fix: `redeemable=false`. On first correct run:
   `was=0.0 now=10.0`, `was=5.0 now=20.0` — bots were tracking 5 while holding 20.
2. **Too fast** — 5s ⇒ HTTP 429 ⇒ intermittent failure ⇒ eth drifted to inv=45 vs a 30 cap.
3. **Shared egress** — both pods leave via one IP; at 15s each, eth logged 11
   consecutive 429s and ZERO reconciles. Fix: 30s **staggered per coin**
   (`hash(COIN)%2*15`) + exponential backoff to 120s.

⇒ **⭐⭐ An unverified safety mechanism is worse than none — it reports healthy
while protecting nothing. Never accept "no errors in the log" as evidence a
guard works; test the code path directly.**

---

## 5. MY OWN ANALYSIS ERRORS (kept deliberately — they cost real time)

| error | how it was caught |
|---|---|
| proposed EDGE_C 1.5→2.5c as "+40% income" | measured: reachable volume halves per cent ⇒ **0.78×**, not 1.4× |
| proposed mint/merge as "a different mechanism" | checked the book: **100% mirrored** ⇒ same order. Had already established this at 5m |
| re-tested exits TWICE after deriving the rule that forbids them | RAND == real both times |
| `cancelfail.py` modelled failed cancels as orders *lingering* | wrong semantics — a failed cancel means the order ALREADY FILLED; the baseline sim already models it |
| "we're down $28.50 real cash" | false alarm — read `/positions` (saturated); `/value` showed $28.68 open. **NET WORTH = free pUSD + /value, always** |
| "two days and ~$56" for the 1h engine | conflated the 5m pilot's loss; 1h was 16h and −$2.45. User corrected me |
| "btc has 12× 429s" | grep matched digits inside order salts/signatures, not HTTP errors |
| residual decomposition −$796 on 2,042 shares | filter let pm-scout's old political bets through (no "M-" in title) |
| first decomposition skipped fully one-sided bars (`len(v)!=2`) | contradicted the wallet ⇒ found and fixed |
| per-coin splits (eth/doge/xrp) treated as signal | dropping them made the sim WORSE ⇒ noise, not structure |

---

## 6. TOOLING BUILT (reusable, `every-tick-single/backtest/mm5m/`)

42 scripts + a 131 MB parquet cache of every print with pre-trade book context
(7 coins 5m, btc/eth 15m, btc 1h).

Key ones: `extract_prints.py` (parameterised by MREC_SUBDIR / MREC_FPREFIX /
MREC_BAR / DERIVE_WINS — ⚠️ dir suffix and file prefix DIFFER per duration,
ledger #21) · `terrain*.py` (field maps) · `queuedyn.py` (queue decay
calibration) · `fairval.py` (σ(tl) + does the model beat the book) ·
`openmm2.py`/`fvmm.py`/`imbmm.py` (5m sim stack) · **`pairceil1h.py` (the
CALIBRATED 1h pair harness — the single most valuable artifact)** ·
`pairsim15.py`.

---

## 7. STILL OPEN

**4h is the only untested duration.** Recorders live since 08-17 (~14 bars as of
08-21 — far too few). Highest pair completion, smallest residual, 6 bars/day so
even a negative result is nearly free. Retest with `pairceil1h.py` (change
BAR/dir/prefix) once ~2 weeks exist.
⚠️ **Temper expectations: the §0 mechanism is duration-INdependent.** A resting
order fills when the mid comes to it at any bar length. 4h wins only if its
spread exceeds the adverse selection — which 5m, 15m and 1h all failed to do.

**Not worth retrying without a new mechanism:** anything that rests passively
and hopes to be filled below the mid.
