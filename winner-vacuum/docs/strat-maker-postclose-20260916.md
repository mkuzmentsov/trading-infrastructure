# VENUE2.md — adverse selection as a function of price, the post-close pool, `deferExec`

**Agent: polymarket-expert, round 2. 2026-09-16. Read-only. No order was placed, nothing
deployed, no live-fleet change proposed.**
Scope: 5m crypto up/down only. Everything labelled **confirmed-live** (observed from the
live API or from our own recorded tape) or **taken-on-docs**.

Data: `every-tick-single/data/pq/{trades,bookev,res,bar}.parquet` — **5,506,780 real prints /
11,838,473 book events, 2026-09-01→09-10**, and a fresh extract of the raw recorder,
**1,395,994 prints, 2026-09-13→09-15**, built here (`v2_fresh.py`). Plus one live bar watched
through its close second-by-second. Scripts in `research/v2_*.py`, output in `research/out/venue2/`.

---

## 0. ANSWER FIRST

**1. Adverse selection IS a function of price — and it moves the wrong way.** In the only unit
this venue has (`p(1−p)`, the unit the fee, the rebate and the spread all live in), the cost of
being a maker **grows monotonically toward the extremes** while the maker's benefit is a constant
**8.4 units**. Cost/benefit goes **2.2× at the mid → 5.5× at 0.96 → 30× at 0.98**. The 0.97–0.99
band where the taker lane lives is the **worst point on the price axis to be a maker**, not the
best. The maker family is now closed for a second, independent reason, and this one does not
depend on the fee schedule at all.

**2. The post-close dump pool is real, is ~$211–264/day across all 7 coins (not $1.4k/day on
btc), and is queued out by four orders of magnitude.** Live, on one bar: the 0.999 bid stack went
from **9,078 shares at T−2s to 165,883 at T+1s** and sat at ~171,000 for the next 74 seconds while
almost nothing traded. Across 10 days and 10,280 real dump prints, the number of shares that ever
arrived **beyond the displayed depth was 0** and `P(print > depth ahead) = 0.00%`. `PM_TE_SNIPE_REST=0`
is correct and should stay 0. The ⛔ in the decision map is right; the "$1.4k/day" archive line is
notional, not profit.

**3. `deferExec` is dead config.** It is a response-shape flag in the *unsigned* `SendOrder`
wrapper (the v2 TS client's only use of it is `if (deferExec) return response;` — skip transaction-hash
polling). Not a matched-order deferral, not a batch-atomicity primitive; Polymarket's own 2026 SDKs
hardcode it `false` and our pinned `py_clob_client 0.34.6` cannot even send it. **Closed.**

---

## 1. TASK 1 — adverse selection as a function of resting price

### 1.1 Why the question is well posed, and the two populations it can be asked of

The one-book identity makes every print a **maker buy**:
`taker SELL tok@px` ⇒ maker bought `tok` at `px`; `taker BUY tok@px` ⇒ maker bought the complement
at `1−px` (`UP ask ≡ 1 − DOWN bid`). So the whole tape is a census of maker fills with a known
terminal payoff. Terminal net for a flat maker = `100·(payoff − q) + rebate`, fee **0**.

There are two different objects and the program has conflated them once already:

* **P — the population of real fills.** What the maker who actually got filled at price `q` banked.
  Includes everyone's cancels, everyone's queue priority. **An upper bound on us.**
* **S — a simulated resting quote.** Place at `mid − Δ`, never cancel, fill on any print through
  the quote. This is the archive's object and it reproduces here: pooled mid-bar
  **−3.26 c/share** on 98,080 fills against the archive's **−4.624 ± 0.382** on 47,038
  (`v2_rest.py`; different placement grid and Δ, same sign and magnitude). **A lower bound on us.**

The gap between P and S is **cancellation**, not price. §1.4 prices it.

### 1.2 The bound (S), re-cut by price — this is the deliverable

`v2_rest.py`, Δ=1.5c, 6 coins, 200,203 quotes, 135,003 fills, 08 placement times per bar.
TERM includes the maker rebate and charges **zero** fee.

| quote band | fill % | **TERM c/share** | maker fee saved | **maker benefit** (fee+rebate) | **cost / benefit** |
|---|---|---|---|---|---|
| 0.00–0.20 | 85.2 | **−1.72** ± 0.14 | 0.591 | 0.709 | **2.4×** |
| 0.20–0.50 | 90.7 | **−4.73** ± 0.21 | 1.612 | 1.934 | **2.4×** |
| 0.50–0.70 | 83.1 | **−4.38** ± 0.30 | 1.683 | 2.020 | **2.2×** |
| 0.70–0.80 | 76.2 | **−4.57** ± 0.44 | 1.308 | 1.570 | **2.9×** |
| 0.80–0.90 | 63.2 | **−3.71** ± 0.39 | 0.878 | 1.054 | **3.5×** |
| 0.90–0.95 | 40.2 | **−2.56** ± 0.41 | 0.465 | 0.558 | **4.6×** |
| 0.95–0.97 | 17.7 | **−1.68** ± 0.53 | 0.254 | 0.305 | **5.5×** |
| **0.97–0.99** | **2.0** | **−6.12** ± 1.29 | 0.170 | 0.204 | **30.0×** |

**Read it in raw cents and you get the wrong answer** ("−4.7 at the mid, −1.7 at 0.96 — it shrinks!").
Read it in the venue's own unit and the shape is unmistakable. `TERM / p(1−p)`:

| band | 0–0.2 | 0.2–0.5 | 0.5–0.7 | 0.7–0.8 | 0.8–0.9 | 0.9–0.95 | 0.95–0.97 | 0.97–0.99 |
|---|---|---|---|---|---|---|---|---|
| **cost** | −20.4 | −20.5 | −18.2 | −24.4 | −29.5 | −38.6 | −46.1 | **−251.6** |
| **benefit** | +8.4 | +8.4 | +8.4 | +8.4 | +8.4 | +8.4 | +8.4 | +8.4 |

**Everything on this venue is priced in `p(1−p)`.** Fee `= 7.0·p(1−p)`; maker rebate `= 1.4·p(1−p)`;
maker benefit `= 8.4·p(1−p)`, exactly. The fee result of round 1 worked because the *mispricing* does
**not** shrink as fast as `p(1−p)` — that is why the taker lane survives at 0.98. Adverse selection
shrinks **slower** than `p(1−p)` too — which is why the same move kills the maker. **The two walls
are not opposite; they are the same wall seen from two sides.**

**The mechanism, in one line:** near an extreme, a resting bid only fills **when the outcome is
changing**. Fill rate collapses 90% → 2.0% from the mid to 0.98, and the payoff is structurally
asymmetric: a bid at 0.98 can win 2c and lose 98c, so it needs **98% of its fills to be harmless**
just to break even. **At the extremes the fill *is* the news.**

**Robustness (pre-registered splits):**
* **Era** (09-01→05 vs 09-06→10): **0 of 16 (band × era) cells positive.**
* **Coin** (6 coins): **2 of 48 cells positive**, both bnb, n < 200 each.
* **Quote depth**: Δ=0.5c instead of 1.5c improves every band (fill rate 67%→71%; pooled 0.95–0.97
  −1.68 → −0.90) and still gives **0/16 era cells and 2/48 coin cells positive**. Quoting tighter
  helps, as the archive said; it does not reach zero. Best single cell in the whole sweep:
  **btc, 0.95–0.97, Δ=0.5c: +0.43 c/share** — before any queue model and before cancel latency.

### 1.3 The cancellation bound — what a *perfect* canceller would earn

`v2_cancel.py`. Same quotes; pull the order when the mid has moved X below it, observed with
latency L (L=0.2s is **faster than the 190 ms venue floor**, so this is a bound, not a plan).
TERM c/share on surviving fills:

| band | no cancel | L=0.2s X=0.5c | L=0.2s X=1c | L=1.0s X=0.5c |
|---|---|---|---|---|
| 0.20–0.50 | −4.73 | −3.97 | −3.90 | −4.31 |
| 0.50–0.70 | −4.38 | −3.14 | −3.17 | −3.75 |
| 0.70–0.80 | −4.56 | −3.61 | −3.64 | −4.20 |
| 0.80–0.90 | −3.71 | −2.78 | −2.67 | −3.48 |
| 0.90–0.95 | −2.56 | −1.60 | −1.66 | −2.43 |
| 0.95–0.97 | −1.68 | **−0.14** | −0.25 | −1.21 |
| 0.97–0.99 | −6.12 | **−8.58** | −7.31 | −7.57 |

* Perfect 200 ms cancellation recovers **~25%** of the loss and **never reaches zero** in any band.
* At 1 second — nearer our real budget, given `rtds_lat` p50 **2.21s** — it recovers ~10%.
* **In the 0.97–0.99 band cancelling makes it WORSE** (−6.12 → −8.58). Cancelling removes the
  benign fills (the ones where the mid never moved) and leaves only the regime changes. This is the
  same statement as §1.2 from the other direction, and it is the cleanest refutation of "maybe a
  faster maker can live at 0.98."

### 1.4 The population (P) — what the *average filled* maker got, and why it is not us

Share-weighted, real fills, in-bar only, 09-01→09-10 (`v2_adv.py`, `v2_side.py`):

| band | **mid-bar** (tl≥60) TERM | **late** (tl<60) TERM | late, 10s markout |
|---|---|---|---|
| 0.20–0.50 | +0.52 | **−3.15** | −2.54 |
| 0.50–0.70 | +0.56 | **+2.64** | +0.33 |
| 0.70–0.80 | −0.56 | **+3.81** | +0.86 |
| 0.80–0.90 | +0.31 | **+2.99** | +0.89 |
| 0.90–0.95 | +0.36 | **+1.95** | +0.71 |
| 0.95–0.97 | +0.35 | **+1.04** | +0.52 |
| 0.97–0.99 | −0.52 | **+0.30** | −0.15 |
| 0.99+ | −0.54 | **+0.14** | +0.05 |

Two facts worth carrying:
* **Mid-bar, the population is flat and near zero in c/share across the entire price axis**
  (−0.6…+0.6). The `p(1−p)` normalisation of *that* is again monotone against the maker.
* **Late-bar the sign flips on the favourite side**, and the population maker-bid edge is
  ≈ **40·p(1−p)** c/share from 0.5 to 0.97 — a strikingly constant multiple (40, 34, 45, 41, 39)
  that decays to +0.75 at 0.97–0.99 and +0.15 at 0.99+. Split by construction (`v2_side.py`),
  the *resting bid on the token* is the good side (0.5–0.7 **+9.93 c/sh, t_day 3.64, 9/10 days**;
  0.97–0.99 **+0.75, t_day 5.31, 9/10 days, $1,020/day pool**), and *resting the ask on the
  complement* is weaker. Era-split: sign holds in both halves for every favourite band.
* Back-of-queue is **not** the penalty here: shares arriving *beyond* the displayed depth score
  **better** (0.5–0.7 +11.45, 0.7–0.8 +10.19, 0.97–0.99 +1.43 c/share), i.e. big late dumps into
  the favourite are less informed, not more. The whole market's overflow is **~$370/day**, and it
  is 5,600–34,000 shares per band over **ten days**.

**Why P is not available to us:** the entire P−S gap (+0.30 vs −6.12 at 0.97–0.99) is cancellation,
and §1.3 shows a *perfect* 200 ms canceller closes ~25% of it. That is the whole of the
"field average ≠ the subset you will get" rule ([[maker-resting-order-wall]], 4 prior deaths),
now measured **as a function of price** rather than asserted. **This is a bound in the direction
the program needs: P is an upper bound and it is already ≤ +0.3 c/share in our lane.**

### 1.5 Verdict on Task 1

**Adverse selection GROWS toward the extremes relative to the maker's benefit, so the family is
closed a second time.** Nothing here reopens. The one cell that is not laughably negative —
btc, 0.95–0.97, 0.5c quote, perfect cancellation — is **+0.43 c/share before queue modelling**,
on a band that supplies ~1,000 fills in ten days across the whole market, i.e. **below the
fleet's own $8.37/day noise floor even if we captured all of it.** Fill-model risk points the
wrong way (the sim gives us the full print).

---

## 2. TASK 2 — the post-close dump pool, re-measured

### 2.1 What it is (confirmed-live, both eras)

| | 09-01→09-10 (10 d) | 09-13→09-15 (3 d, fresh) |
|---|---|---|
| winner dumps, T+2 onward | 10,280 prints, **54,526 sh/day** | 3,373 prints, **40,302 sh/day** |
| **maker pool, total** | **$263.92/day** (0.484 c/share) | **$211.12/day** (0.524 c/share) |
| — coarse-tick bars (tick 0.01, dumps at **0.990**) | **$176.75/day, 1.022 c/share**, 18,612 sh/day | **$131.37/day, 1.000 c/share**, 13,137 sh/day |
| — fine-tick bars (tick 0.001, dumps at **0.998–0.999**) | **$93.23/day, 0.245 c/share**, 37,977 sh/day | **$79.74/day, 0.294 c/share**, 27,165 sh/day |
| btc share of the pool | $154/day of $177 coarse | **$190/day of $211 total** |
| coarse bars with **any** post-close dump | **11.3%** | **11.2%** |
| day-clustered | mean $176.75/day, **t = 6.94, 10/10 days positive** | — |

99.9% of the dumped shares print at exactly **0.990** or **0.999** — the two tick-regime touches.
Prints labelled `taker SELL of the winner` are 21% of post-close shares; the archive's "99.98%
sellers" is not in conflict — under the mirroring, `sell UP at 0.999` and `buy DOWN at 0.001` are
the same economic event and PM labels by whatever the taker submitted. The measure priced above is
the economic one (**a flat maker ends up long the winner near 1.00**), and it is side-label-free.

**Reconciling the two archive readings:** they are consistent once you separate notional from
edge. ~1.67M shares of post-close flow is right in order of magnitude (I see 2.66M shares in 10
days) — at ~$0.99 that is ~$1.5M of *notional*, which is where "$1.4k/day on btc" came from. The
*edge* is 1 c/share, so the pool is **$177–264/day**, and the ⛔ ("$187 of the $217/day pool is in
coarse-tick bars") is **confirmed**: I measure $131–177 of $211–264 coarse. **Use the ⛔, not the
$1.4k line.**

### 2.2 The kill: the queue, measured three ways

1. **On every real dump print** (`v2_postq.py`, 10,280 prints, 99.8% at the touch):
   median **depth ahead 150,192 shares** (coarse) / **162,486** (fine);
   **P(print > depth ahead) = 0.00%**; **total overflow shares in 10 days = 0**; overflow $ = **$0.00**.
2. **Queue build-up around the close** (`v2_queuetime.py`, winner token, 11.8M book events):
   median top-bid size **504 sh at T−5..0**, **26,523 at T+0..+5**, **111,681 at T+5..+15**,
   **129,073 at T+15..+30**. The wall is built in the **first five seconds**.
3. **Live, one bar watched second-by-second** (`v2_closewatch.py`, btc-updown-5m-1789506600):

```
t  -6s  book bid=0.999 sz=9,068    ask=None
t  -2s  book bid=0.999 sz=9,078    ask=None     (outcomePrices flip to 0.9995/0.0005)
t  +1s  book bid=0.999 sz=165,883  ask=None     <-- +157,000 shares in three seconds
t +14s  book bid=0.999 sz=168,822
t +74s  book bid=0.999 sz=171,099               <-- essentially nothing consumed in 74s
```

Mean arriving dump flow is **11 shares per coarse bar**. The standing queue at the moment
`PM_TE_SNIPE_REST` would place (T+2) is **~26,500 shares**. That is a ratio of **~2,400:1**.
A $12 clip is 12 shares. **P(fill) is indistinguishable from zero, which is exactly what the
live record already said (taker snipe 0/205 era-wide).**

The only door is to be at the level *before* the close — and the wall is already 9,000–16,700
shares deep at T−23…T−2 **on a bar gamma was still pricing at 0.515/0.485**, i.e. people rest at
0.999 through the whole bar regardless of the outcome (this is the same level as the `mintsalvage`
1¢ salvage wall: a 0.999 bid on UP and a 0.001 ask on DOWN are the *same order set* — the live
book returns them mirrored, `UP nbid 111 / nask 0` against `DOWN nbid 0 / nask 111`, identical sizes).

### 2.3 What the risk actually is — precisely

The brief is right that it is **not** adverse selection on the outcome. Naming the real ones:

* **Winner-identification risk — this is the binding one and it is arithmetic.** Buying at 0.99
  wins **+1.0c** and loses **−99.0c**, so break-even accuracy is **exactly 99.0%**. At the
  documented T+2 detection rate (99.98%) the expected value is +0.98 c/share; at 99.5% it is
  +0.505; at 99.0% it is **zero**. There is no margin for a bad tick-completeness guard. Measured
  cost of the wrong side in the tape: 5 prints in 10 days, 17 sh/day, mean price 0.979, **−$16.60/day**
  of realised loss for whoever took them — i.e. the tail is small but it is one-sided and 100× the gain.
* **Settlement/redemption: real but negligible.** Resolution lands a median of **305 s after close**
  (p10 173 s, p90 409 s, p99 454 s, max 604 s; `res.parquet`, 20,870 bars). Capital is locked 99c
  for ~5 minutes to earn 1c — a ~1% return per 5 minutes, so the capital cost is nil, and the
  chaining identity held 2,237/2,237, so oracle risk is nil. **Books are cleared at resolution**
  (a resolved market returns an empty book), which bounds the post-close window at ~300 s and
  matches the tape (max observed print T+513 s).
* **Queue position: the whole of the problem.** §2.2.
* **Exit is irrelevant** — the ⛔'s "≥0.999 demand after a fill in 0.8% of bars" measures *selling*
  the position. You do not sell; you redeem at 1.00. That clause should not be used as a kill;
  §2.2 is the kill.
* **Venue permission is NOT the constraint (confirmed-live):** `acceptingOrders` stayed `true` and
  `closed` `false` on both gamma and CLOB at **every poll from T−23s to T+74s**. Post-close order
  entry is permitted. It is simply pointless.

### 2.4 Verdict on Task 2

**The pool is real, small, and provably unreachable. Leave `PM_TE_SNIPE_REST=0`.** The correct
summary for the decision map is not "a $1.4k/day fee-free maker lane we are not using" but
**"a $211–264/day market-wide pool behind a queue 2,400× the arriving flow; measured capture 0
shares in 10 days."** If a strategy agent wants to revisit it, the *only* live question is whether
a pre-close placement can win the T+0 race — and that converts the lane from risk-free to a
directional bet with a hard **99.0% break-even accuracy**, which is a different (and worse)
strategy than the one that was specced.

---

## 3. TASK 3 — `deferExec`, closed

Full source/API sweep (delegated, all sources re-checkable):

* **Confirmed-live.** Boolean, optional, default `false`, in the **`SendOrder` wrapper**, *outside*
  the EIP-712-signed `Order` struct ⇒ **unsigned wire metadata; it cannot affect exchange-contract
  behaviour.** Per-element on `POST /orders` (max 15, "processed in parallel"), **not** a top-level
  batch flag ⇒ **not an atomicity primitive**.
* **Confirmed-live, the decisive line.** `Polymarket/clob-client-v2` `src/client.ts` L1187-1190:
  `if (deferExec) { return response; }` — its *only* effect is to skip `resolveTransactionsHashes`.
  Tests are literally named `"does not poll for deferExec orders"`. The v1.1.0 release note
  (17 Jul 2026) carves it out of the `transactionsHashes` → `tradeIDs` change.
* **Confirmed-live, safe probe** (unauthenticated / bogus-L2 only, **no signed order, nothing
  created**): the server strictly type-validates it (`deferExec:"yes"` → `400 Invalid order payload`)
  but never produces a `deferExec`-specific code path; unknown sibling fields are silently ignored;
  `clob.polymarket.com` answers 401/400 from this egress, **not** 403.
* **Not ours to use anyway.** `py_clob_client 0.34.6` (what we run) has **zero** occurrences of it.
  Polymarket's own `py-sdk` and `ts-sdk` **hardcode `false`**. Origin: PR #165, 2025-06-12, empty
  body, no rationale ever published. Not in any changelog. The one third-party doc that describes it
  (`bububa/polymarket-client`) is **wrong** — it confuses it with `postOnly`.
* **Do not chase the latency hypothesis.** We run the v1 client, which never polled for hashes, so
  there is no polling cost to remove; and if it does what the name says, it makes a FAK fill result
  **non-synchronous**, which is strictly worse for a bot that must know its fill immediately.

⚠️ **`delayed` in `SendOrderResponse.status` is not `deferExec`** — the spec pairs it with rate-limit
errors, and the taker-delay mechanism is the market flag `itode` (documented as a **250 ms** hold for
marketable orders; `true` on 20/20 5m crypto markets, incl. pre-open).

**Downgrade `strat-venue-fees-20260915.md` §4 from "the only genuinely unexplored order-submission
flag" to "internal plumbing flag, characterised, closed."**

---

## 4. Corrections and additions to my own VENUE.md

1. **§6 line 2 was under-specified.** "Be the maker … closed by adverse selection (−4.6 c/sh)" was a
   mid-bar mid-band number, as the brief suspected. The correct statement is now **§1.2**: the maker's
   benefit is exactly `8.4·p(1−p)` and adverse selection is `18–46·p(1−p)` (and `250·p(1−p)` at 0.98).
   **The maker door is shut at every price, and shut hardest where we actually trade.**
2. **New venue detail (confirmed-live, and a sim trap):** `minimum_tick_size` on the CLOB market
   object and `orderPriceMinTickSize` on gamma **both read 0.01 on a market whose live book was
   quoting 0.999**, before and after its close. **The REST tick fields are the configured floor,
   not the in-force tick** — only the WS `tick_size_change` event (or 3-decimal prices in the book)
   tells you the truth. This strengthens bug #39 rather than adding a new one.
3. **New venue detail:** a resolved market's **book is cleared** (empty `bids`/`asks`), while an
   unresolved but closed market keeps `acceptingOrders: true` and `closed: false`. The tradeable
   post-close window is therefore bounded by resolution, p50 **305 s**.
4. **The one-book mirroring is exact in the REST book too**: `UP nbid 111 / nask 0` vs
   `DOWN nbid 0 / nask 111` with identical sizes level-for-level. A "0.999 bid queue on the winner"
   and a "0.001 salvage ask stack on the loser" are the same object; do not count them twice.

## 5. Files

* `research/VENUE2.md` (this file)
* `research/v2_adv.py`, `v2_adv2.py`, `v2_mid.py`, `v2_side.py`, `v2_queue.py` — Task 1 population
* `research/v2_rest.py`, `v2_cancel.py` — Task 1 bound (`out/venue2/rest_era.txt`, `rest_d005.txt`, `cancel.txt`)
* `research/v2_post.py`, `v2_postq.py`, `v2_queuetime.py`, `v2_preplace.py`, `v2_closewatch.py`,
  `v2_fresh.py` — Task 2 (`out/venue2/closewatch.txt`, `fresh.txt`)
* derived: `research/data/mfills.parquet`, `mfills2.parquet` (5.4M maker-fill rows with mid,
  markouts and terminal payoff), `mfresh.parquet` (09-13→15)
