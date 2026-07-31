# Arb / post-order rebate farmer — print-exact investigation (2026-07-31)

Data: mrec 100ms recorder, **4,860 resolved markets**, 6 coins, 27–30 Jul, full
top-of-book both tokens + every trade print + ground-truth resolution. Every
number below is a FIFO-queue simulation against **real taker prints** — not the
1-minute mid proxy that produced the earlier "pre-open two-sided ≈ breakeven"
estimate in `PLAN.md`.

## TL;DR

Every configuration is negative. Two are negative at overwhelming significance,
and the fill model is separately shown to be ~10× **optimistic**, so the true
results are worse than the table. **Do not deploy live.**

## 1. Pair-lock farmer (bid both tokens, cancel unfilled at bar open)

| entry | price | bars | both% | LOCK$ | REBATE$ | directional$ | t | EDGE$ | noise σ$ |
|---|---|---|---|---|---|---|---|---|---|
| next3 | 0.50/0.50 | 522 | 21% | 0.00 | +48.41 | +43.39 | +0.10 | **+48.41** | 430 |
| next3 | 0.51/0.51 | 545 | 22% | −25.98 | +53.83 | −124.17 | −0.27 | +27.85 | 456 |
| next3 | 0.49/0.49 | 364 | 6% | +5.98 | +27.79 | +5.16 | +0.02 | +33.77 | 337 |

**The positive result:** unpaired pre-open fills are **unbiased** — |t| < 1 at
every price, every window (single-fill win rate 48–50%). This is the first
print-exact confirmation of the pre-open hypothesis and it kills adverse
selection as the pre-open explanation. Held to expiry it is 4% (t ≈ −40).

**Why it still fails:** both-fill rate and lock value are inversely coupled. The
only price with real both-fill (0.51) pays $1.02 for a $1 pair; the only prices
that lock (≤0.49) fill 2–6% of bars. At 0.50 the lock is exactly zero by
construction, so the entire edge is the rebate: **+$48 over 4 days against $430
of noise.** Reaching 2σ confidence needs ~320× more data ≈ 3.5 years.

## 2. Maker round-trip (buy at bid as maker → sell at ask as maker)

The shape that matches "post order rebate farmer" most literally: both fills are
maker fills (rebate on each), position ends flat, no pair required.

*Constraint the naive version misses: you cannot buy 0.50 and sell 0.50 and call
both maker. On a 0.50/0.51 book a 0.50 sell crosses and pays the 0.07·p(1−p)
taker fee = **1.75c/share at 50c, 5× the rebate**. The exit must rest at the ask.*

```
buy0.50 → sell0.51   entries=632  exit_rate=90%
  spread +$124.36  rebate +$91.92  DETERMINISTIC +$216.28
  stuck residual −$697.88 (n=61)   noise σ=$122  →  t = −5.7
  TOTAL −$481.60
```

| | entries | net/entry |
|---|---|---|
| completed round trips | 571 | **+$0.369** |
| stuck with inventory | 61 | **−$11.35** |

**One stuck entry erases 31 completed ones.** Break-even requires the rebate to
be **5.2× larger**, or the stuck rate to fall from 9.7% to **2.9%**.

Force-flatting the stuck inventory is worse at every deadline (cutting at bar
open drops exit rate to 25% and loses −$452 at t ≈ −10): you pay spread + taker
fee on three quarters of the book to avoid the tail.

No entry-time observable separates stuck from completed. Bucketed by spread,
depth and imbalance, the stuck rate moves only 6.8% → 13.3% — never near 2.9%,
and every bucket with n > 100 is negative.

## 3. Canonical two-sided market making (bid + ask on one token)

8,167 market-tokens, 180,588 fills: **−$113,459, t = −41**. The decomposition is
the same story in the extreme: markets ending **flat** earn +$4,291; markets
ending **with inventory** lose everything and more. (This variant re-posts at
fixed prices as the market runs, so it overstates the loss — but the realistic
capped round trip in §2 is already −5.7σ.)

## 4. ⚠️ THE FILL MODEL IS ~10× OPTIMISTIC — validated against live

Pointing the identical model at the config `btc-vacuum` actually ran live on
30 Jul (rest a 0.99 maker bid on the locked winner, 45s before close):

```
simulated : 630/816 bars filled = 77.2%
LIVE      :  13/165 rests filled =  7.9%
ratio     : 9.8x too optimistic
```

The recorder only gives **top of book**. When our quote is not exactly at the
best bid the model assumes an empty queue and grants a fill on any print at or
through our price, while in reality we sit behind a wall we cannot see. This is
the same blindness that made the old mid proxy overstate the both-fill rate — it
is smaller here, but it is not gone.

Per-**share** economics (rebate 0.665c, net −3.482c) are what decide viability
and they are not fixed by a fill-count correction; the sign of every result
above is unchanged, and the true volume is ~10× lower than modelled.

### 4b. Sensitivity — the conclusion survives the whole uncertainty range

Calibrating the unobservable queue against the live 0.99 result gives ~3,000
shares hidden at that level. Rather than transplant that number to 0.50, sweep
it (round trip buy 0.50 → sell 0.51):

| hidden queue | entries | exit% | deterministic$ | residual$ | TOTAL$ |
|---|---|---|---|---|---|
| 0 sh | 632 | 90% | +216.28 | −697.88 | **−481.60** |
| 100 sh | 53 | 91% | +55.56 | −149.38 | **−93.82** |
| 300 sh | 13 | 99% | +16.74 | −2.83 | +13.92 |
| 1,000 sh | 2 | 100% | +3.40 | 0.00 | +3.40 |
| 3,000 sh | 0 | — | — | — | no entries |

**Both branches fail, for different reasons.** If the queue is small we trade
often and lose to the inventory tail. If the queue is large the tail disappears
but so does the business — 13 entries in 4 days across 6 coins is 3 fills/day,
and the "+$13.92" is one unstuck entry away from noise. There is no queue
assumption under which this is both profitable and worth running.

## 4c. TAKER pair arb (what the stopped `bnb-pa` bot does)

Same data, different question: how often is `ask_UP + ask_DOWN + fees < $1`?

```
1Hz two-sided observations : 5,664,337
  ua+da < 1.00 (gross)     :   669  (0.012%)
  edge >= 0.5c after fees  :   316  (0.0056%)  ~79/day across 6 coins
  depth at those moments   :  median 6sh, p90 11sh, max 50sh
```

Theoretical **maximum** capture — perfect execution, zero latency, catching
every single crossing — is **$21.65/day**, mean $0.274 per opportunity. btc
never qualifies once; doge is 166 of the 316 and its crossings are the shortest
lived (median 0.71s per the earlier latency study).

Against that, the measured cost of one legged fill on 30 Jul was **−$2.55**, so
the break-even both-leg fill rate is **90.3%**. The one live attempt legged
(0/1). An opportunity worth 27c cannot fund a 255c failure at anything less
than near-perfect execution.

## 4d. SEQUENTIAL pair + active neutraliser (user's mechanism, 31 Jul)

Proposal: don't buy both sides at once. Rest bids on both, and when one fills,
immediately either complete the pair or dump the filled side — minimising the
time spent one-sided rather than riding it to resolution. Tested in `seqpair.py`
over each market's full life (tl 1200 → 0, so the price has ~20 min to
oscillate into both levels).

**The insight is correct and it is the single biggest improvement found:**

| bids | ride to resolution | complete @0.2s |
|---|---|---|
| 0.50/0.50 | −$9.65/bar | **−$2.04/bar** |
| 0.48/0.48 | −$9.35/bar | **−$1.60/bar** |
| 0.45/0.45 | −$8.39/bar | **−$0.72/bar** |

A ~93% reduction in loss. Riding an unpaired leg is a ±50c/share coin flip;
neutralising caps it at a few cents.

**Two structural facts fell out.**

1. **Completing the pair and dumping the position are mathematically
   identical** — same result to the cent, because `bid_this ≈ 1 − ask_other` for
   complementary tokens. Buying the complement *is* selling the token. There is
   no choice to optimise.

2. **The residual cost is 80% adverse move, only 20% fee.** Decomposed at 0.2s
   reaction: raw pair economics −2.7c/share, taker fee −0.6c/share. Our maker
   fill *is* the signal that the price moved, so by the time we react the
   complement has already repriced and the pair costs ~$1.027. **Zero-fee
   execution would not fix this.**

### The deep-bid trap — a positive result that was an artifact

Sweeping deeper made the loss shrink and then cross into profit: 0.42 breakeven,
0.30/0.30 showing **+$0.90/bar at t = +6.53** over 4,759 bars. It is not real.
At those prices our bid sits **below the touch in ~100% of entries** — the exact
configuration where §4 proved the model 10× optimistic. Adding hidden queue:

| price | hidden=0 | hidden=50 | hidden=200 | hidden=1000 |
|---|---|---|---|---|
| 0.30 | +$0.90/bar (t=+6.5) | **−$3.73** (t=−8.0) | −$7.07 | −$16.71 |
| 0.35 | +$0.69/bar (t=+5.6) | **−$5.13** (t=−11.8) | −$8.66 | −$19.57 |

**Fifty shares of queue flips it from +6.5σ to −8σ.** The mechanism is worth
naming: a queue ahead of us filters out the small benign prints and leaves only
the large sweeps — the informed ones. Queue depth is *adverse-selection
amplifying*, so a resting order deep in the book is reached only by the flow you
least want to trade against.

## 4e. MAKER-MAKER sequential + rescue + low-vol gate (user v2, 31 Jul)

Refined mechanism: post ONE bid in anticipation of a dip; when it fills, post
the complement as a SECOND maker order (both legs earn rebate — the farm);
market-order rescue only if the second leg doesn't fill; hypothesis that this
works in low-volatility bars. `seqmaker.py`, hidden=50sh everywhere.

**Rescue-timing tension (measured, p1=0.48/p2=0.52):** rescue 5s after the fill
→ 99% of bars pay the taker rescue and only 1% ever achieve the maker-maker
pair (−$15.07/bar). Wait until tl=30 → mm-pair rate rises to 27% but trend
bars' rescue ask has run away (−$10.08/bar). Every point between: −$14 to −$10.
There is no good rescue time; both horns lose.

**The low-vol hypothesis fails for a structural reason, not a tuning one.**
First attempt at bucketing exposed it: EVERY bar that produced a first fill
lands in the highest-vol bucket — a fill at 0.48 requires a ≥4c swing, so the
entry itself selects the regime the strategy wants to avoid. The fill IS a
high-vol event. And with the honest chop proxy (range of the first half of the
active bar, before resolution convergence dominates):

```
median first-half range = 0.42;  p25 = 0.34    <- there IS no low-vol regime
LOW  (≤0.10): 3 bars in 4,849   (fills ~never happen in quiet bars)
MID  (≤0.25): 117 bars, −$11.84/bar (t=−6.5)
HIGH (>0.25): 1,552 bars, −$9.98/bar (t=−21.3)
```

**Structural conclusion:** a 5m binary is forced to converge to 0 or 1 within
minutes — the median bar moves the book 42c in the first 2.5 minutes of the
active window. The oscillate-around-50c market this mechanism needs does not
exist in these instruments. The strategy shape (maker-maker pair + rescue) is
coherent; the instrument contradicts it. If it has a home, it is slower
markets: hourly/daily up-downs or non-crypto markets that genuinely sit near
50c with two-sided flow — none of which the current recorder covers.

## 4f. The slow-market escape hatch, measured (politics/finance, 31 Jul)

Category rates (verified from docs 31 Jul): crypto fee 0.07 / rebate 20%
(0.35c/sh at 50c); politics & finance 0.04 / 25% (0.25c/sh); sports 0.05 / 15%
(0.19c/sh); **geopolitics fee-free → no pool at all** (excludes the biggest
"stable mid" markets — Iran, Taiwan, ceasefires).

Case study on the best available candidate — the Sept-2026 Fed no-change market
($1.46M/24h "headline" volume, 1c spread, mid ~0.445): 6,918 prints across 79
days, plus the live book.

```
median daily volume        6,263 sh    (the $1.46M day was FOMC — 100x median)
median daily REBATE POOL   $15.47      <- the WHOLE market's pool, ALL makers
days with >=10c repricing  13%
median flow imbalance      |sell%-50| = 30pp  (flow is one-sided even on quiet days)
book at the touch          33.5k bid / 11k ask resting ahead of any new quote
```

Three independent killers:
1. **The pool is tiny.** $15/day for the entire market, shared by weight. With
   33.5k shares already at the bid, a 1k-share quoter owns ~3% of the queue →
   cents per day. Even 100% capture cannot fund a strategy.
2. **The pool is big exactly when farming is deadly.** Pool ∝ volume; volume
   spikes on repricing days (FOMC day: $3,687 pool, 8-46c ranges). The fee
   revenue and the inventory toxicity are the same variable.
3. **Flow is one-sided even when price is flat** (median imbalance 30pp), so
   two-sided quotes don't cycle — they accumulate the drift side. Same adverse
   selection as crypto, on a slower clock.

## 5. The general bound (why no variant can work)

Rebate farming as a PRIMARY strategy is capped by an identity: the pool is
20-25% of taker fees **in that market**. Taker fees come attached to the flow
that repriced the market. So either
  - the market is calm → fees ≈ 0 → pool ≈ 0 (politics median: $15/day), or
  - the pool is large → the market is fast → maker inventory is toxic
    (crypto 5m: every configuration −5σ to −40σ).
The rebate is a partial refund on adverse selection, structurally smaller than
the loss that generates it. It can subsidise an ALREADY-profitable maker
operation by ~0.25-0.35c/share; it cannot BE the strategy.

## 4g. Crypto-only completion (31 Jul, morning)

**Slow crypto instruments** (same 0.07/20% category, slower clock):
- Daily threshold markets (`bitcoin-above-66k-on-july-31`): mid-priced days
  have **$0.19-2.19/day** pools — volume only arrives near expiry, at the
  tails, converging. Dead.
- Daily up/down (`bitcoin-up-or-down-on-july-31`): **$106-117/day pool while
  mid-priced** — the best crypto pool found — but taker flow is **96% BUYS**
  (shorting UP = buying DOWN; taker sells barely exist). Resting bids farm 4%
  of the flow. Series total pool ~$100/day bounds any capture.

**Mint + dual-ask farmer** (`msell.py`) — the mirror config the 96% buy flow
suggests: split $1 into UP+DOWN fee-free, rest maker asks on both tokens at
aU+aD = 1+margin. Never tested before tonight. Result: the **worst of all
seven configs** — both-fill 47-54% (flow is indeed there) and the largest
rebate haul of any run (+$2,316), yet **−$22/bar at t = −65**. The buyers
lifting our asks are informed direction-takers: they buy the winner from us at
0.51-0.53 and leave us holding its complement. Flow abundance was never the
constraint — flow toxicity is, identically on both sides of the book.

**The one clean config, sized honestly.** Pre-open 0.50/0.50, cancel at open
(unbiased fills, |t| < 1 — §1) under the hidden-queue haircut:

| hidden queue | bars traded | shares | REBATE (4 days) | direction t |
|---|---|---|---|---|
| 0 | 522 | 13,832 | +$48.41 | +0.10 |
| 50 | 92 | 5,753 | +$20.14 | +0.58 |
| 200 | 20 | 1,534 | +$5.37 | +0.58 |

Clean rebate income at realistic queue: **~$1-5/day** across all six coins at
100sh/side, direction-neutral by construction, carried on ±$250/day of
zero-mean coin-flip variance. Real, deployable, and economically pointless.
Every attempt to push volume beyond this window buys adverse selection at
5-60× the rebate.

## 6. Conclusion

The rebate is real, deterministic and far too small: **0.665c/share round trip
against a 50c/share coin flip whenever the exit does not fill.** The strategy
needs the inventory tail to essentially vanish, and nothing observable predicts
it. This is consistent with, and now quantifies, the prior live results
(`pm-rebates-farmer` decommissioned, `every-tick-both` deleted, the 0.98 maker
tier pulled at −$7.29/152 bars).

**What would change the answer** — none of which we control today:
1. rebate ≥ 5× current (pool share, or a market where we are most of the maker weight);
2. fee-free or rebated *taker* exits, removing the 1.75c cost of flattening;
3. genuine queue priority (co-location at the matching engine / API-level priority),
   which is the only thing that could push the exit rate from 90% toward 100%.

**Recommendation: do not deploy live.** The one thing a live probe would buy is
a real measurement of queue position — the single quantity this dataset cannot
provide (§4). That is a measurement cost, not an edge, and it should be an
explicit decision with the expected loss stated, not a silent start.
