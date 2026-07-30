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

## 5. Conclusion

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
