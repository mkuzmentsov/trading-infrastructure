# Mint a pair for $1, then MARKET-SELL one or both legs — 2026-09-07

User: *"what about split/merge — generate 2 coins at $1 and then market sell one of them or both
with market order?"* Scripts: `scratchpad/verify/mintsell.py` + the cross-book census.

**VERDICT: ⛔ DEAD by identity, with one exception that is a phantom.**

## 1. The arithmetic, before any data
`ua ≡ 1 − db` and `da ≡ 1 − ub` (the two token books are one book). Therefore:
- **Selling BOTH legs yields `ub + db = 1 − spread`.** You paid $1 to mint ⇒
  **net = −spread − two taker fees, guaranteed.**
- **Minting then selling ONE leg** leaves a cost basis of `1 − ub + fee(ub)` on the other side.
  Since `da = 1 − ub` and `fee(ub) = 0.07·ub(1−ub) = 0.07·da(1−da) = fee(da)`, that is **exactly
  `da + fee(da)` — identical to simply buying the other side at its ask.** The mint is a cash
  no-op; it cannot improve a price.

## 2. Measured, btc, 3,287,651 book states
Identity holds: `|ub+db − (1−spread)|` max 3e-2 (one tick of rounding); `mint-then-sell-UP` vs
`just-buy-DOWN` max difference **2e-02**, i.e. identical to the tick.

**Mint + market-sell BOTH, net per $1 minted after both taker fees:
mean −3.812c, median −3.852c.** Proceeds median $0.99 for a $1 outlay.
Gas via the CtfCollateralAdapter is ~0.02 c/share — negligible, and not the reason this fails.

## 3. The only exception — a CROSSED book — and why it is not money
`proceeds > $1` requires `spread < 0`. Those states exist: all 7 coins, 22,455,779 states,
**13,993 crossed (0.0623%)**, of which **9,603 profitable after fees (0.0428%)** —
**336 distinct (coin, bar) episodes over 11.6 days**, theoretical **$148.76 = $12.84/day** taking
one clip per episode at the displayed size. That is comparable to the whole fleet's ~$14/day, so
it was worth checking properly.

**It is the phantom layer (bug #23 addendum), not a venue state:**
- **Only 28.3% of the 336 episodes have ANY real SELL print in `[t0−0.5s, t1+0.5s]`. The median
  episode has ZERO prints.** A genuine 20-30c risk-free arb standing for 0.2-88 seconds would be
  taken instantly by the whole market. Nobody traded it.
- The distribution is a handful of tiny quotes: median episode value **$0.13**, median displayed
  size **5 shares**, median duration **1.0s**; only 35 episodes worth >$1 and 3 worth >$5.
- The identity `ua = 1−db` holds exactly on these states (median gap 0.0000, 0.0% above 0.005),
  so the two token books are NOT out of sync with each other — it is the UP book's own ask sitting
  below its own bid, i.e. a stale level the recorder had not yet seen removed. `evage` is 0.01-0.10s
  (events were arriving) — **`evage` measures event recency, not book correctness, and does not
  detect this.**

**Conclusion: mint-and-sell cannot beat simply trading the book, because the mint is a cash no-op
and selling both legs pays the spread twice over. The crossed-book exception is untakeable
displayed liquidity.** Related: `strat-btc5m-scan-20260907.md` (mint as the *completing* leg with a
maker exit: −3.250 ± 0.337 c/share, 0/6 days) and bug #23.

## 4. What WOULD have made it work, for the record
A pre-minted pair is risk-free inventory (redeems at $1), so latency on the mint is not the
obstacle — you could hold inventory and sell into a cross. The obstacle is that the crosses are
not takeable. If a future recorder change lets us verify takeability in real time (logging the
displayed size **and** whether a print followed), this census can be re-run cheaply; the standing
number to beat is **336 episodes / 11.6 days, 28.3% with any print at all.**
