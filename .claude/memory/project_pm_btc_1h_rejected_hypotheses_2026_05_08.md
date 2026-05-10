---
name: PM BTC 1h rejected hypotheses log 2026-05-08
description: Index of hypotheses tested and rejected on 2026-05-08 — chop_ratio_30m gate, entry-band sweep (FLOOR × CEIL), Kelly sizing amplification, hour-of-day filter. Don't re-run these without new data.
type: project
---

Single-day session generated multiple hypotheses about how to fix the −$363 corpus bleed. Most were rejected. This file is the compendium so future-me doesn't re-litigate them.

## 1. CHOP regime gate — rejected

**Hypothesis (from 27h bundle alone):** when BTCUSDT hourly `realized_vol / |drift|` ratio > 3.0, recent UP entries lose. Build a regime-detector to block CHOP hours.

**Method:** for each open in 4-bundle corpus (n=271), computed `chop_ratio_30m = sigma_5m × √6 / |ret_30m|` from entry-time data. Bucketed PnL by ratio.

**Result:** the corpus does NOT support the hypothesis.

| Bucket | n | PnL | Mean |
|---|---|---|---|
| TREND <1.0 | 93 | **−$194** | −$2.09 ← worst |
| TREND 1.0-1.5 | 54 | −$76 | −$1.40 |
| MIXED 1.5-2.0 | 37 | +$14 | +$0.37 ← best |
| MIXED 2.0-3.0 | 35 | −$74 | −$2.12 |
| **CHOP 3.0-5.0** | **22** | **+$10** | **+$0.47** ← actually a winner |
| CHOP 5-10 | 14 | −$37 | −$2.61 |
| CHOP >10 | 16 | −$7 | −$0.42 |

The 27h-bundle "CHOP fingerprint" was a regime-specific cluster of 5 trades. Across 271 trades, **CHOP 3-5 is actually a small winner**, and the worst bucket is TREND<1.0 (very-trendy hours where the bot enters at price extremes and gets mean-reverted).

**How to apply:** don't ship a chop_ratio gate. The signal is non-monotonic with PnL.

## 2. Entry-band sweep (FLOOR × CEIL) — rejected

**Hypothesis (from worst-trade analysis):** entry prices at the tails (<0.62 or >0.70) bleed disproportionately. Naive analysis suggested blocking `(entry < 0.62 OR entry > 0.70)` would save +$251 corpus-wide.

**Method:** sweep `SMART_ENTRY_FLOOR ∈ {0.30, 0.55, 0.60, 0.62, 0.65}` × `SMART_ENTRY_CEIL ∈ {0.68, 0.70, 0.72}` = 15 cells × 5 bundles = 75 replay runs.

**Result:** production (FLOOR=0.30, CEIL=0.70) is the corpus optimum at +$169.82. Naive +$251 collapsed to **−$62 absolute** in actual replay. The bot reroutes to other entries when preferred ones are blocked.

Top 5 cells:
| FLOOR | CEIL | n | PnL | per-bundle (111h / 22h / 7h / 26h / 27h) |
|---|---|---|---|---|
| 0.30 | 0.70 | 137 | +$169.82 | +170.90 / +11.40 / +10.02 / −4.91 / −17.59 ← prod |
| 0.30 | 0.68 | 122 | +$160.95 | +166.47 / +8.29 / +10.44 / −12.49 / −11.76 |
| 0.55 | 0.70 | 131 | +$135.84 | +108.52 / +20.90 / +10.02 / +13.99 / −17.59 |
| 0.30 | 0.72 | 151 | +$130.21 | +125.01 / +10.98 / +10.02 / +2.38 / −18.18 |
| 0.55 | 0.68 | 116 | +$126.97 | +104.09 / +17.79 / +10.44 / +6.41 / −11.76 |

Bundles disagree dramatically: 26.7h *gains* $52 from tighter FLOOR (+$47 at 0.62), 27h *loses* $54 in the same direction. No single static config beats prod across all bundles.

**How to apply:** the 4th sweep this week to conclude "production is the corpus optimum, knob retunes don't help." Don't sweep entry bands again.

## 3. Kelly sizing amplification — rejected

**Hypothesis:** Kelly might scale catastrophes UP and wins DOWN, since high p_up → high Kelly → big bet, and high-p_up bets are mean-reverters.

**Method:** computed `invested_$` for each trade and compared distributions of catastrophes (pnl < −$5) vs big wins (pnl > +$5).

**Result:** within each bundle, sizing is essentially identical between catastrophes and wins. The bet cap binds for nearly all trades.

| Bundle | Cat mean inv | Win mean inv | Diff |
|---|---|---|---|
| 111h (May 4) | $9.51 | $9.84 | −$0.34 |
| 26.7h (May 6) | $20.90 | $22.04 | −$1.14 |
| 27h (May 7) | $21.60 | $21.23 | +$0.38 |

In the 27h bundle, every trade is $19-23 invested. Kelly never differentiates because the cap clips first.

**How to apply:** don't change `kellyScale`. Lowering `betSizeMax` would halve both wins and losses proportionally — same sign on PnL, less variance. Possible but doesn't fix the structural bleed.

## 4. Hour-of-day filter — noisy, partial signal

**Method:** bucketed corpus PnL by 4h UTC windows.

**Result:**

| Window UTC | n | PnL | mean |
|---|---|---|---|
| 00-04 | 47 | −$43 | −$0.92 |
| 04-08 | 44 | −$30 | −$0.68 |
| 08-12 | 43 | −$77 | −$1.79 |
| 12-16 | 45 | −$30 | −$0.66 |
| **16-20** | **49** | **−$113** | **−$2.32** ← worst |
| **20-24** | **43** | **+$8** | **+$0.18** ← only winner |

UTC 16-20 is the worst (peak NYC trading 12:00-16:00 EDT). UTC 20-24 is the only profitable window. Naive blocking of UTC 16-20 saves +$113.

**Caveats:** n=43-49 per window is small. Pattern could be regime-driven (recent BTC has been chop-y during US hours). Hour signal also overlaps with the [killer quadrant](project_pm_btc_1h_killer_quadrant_2026_05_08.md) sigma signal — high sigma tends to cluster during US hours.

**How to apply:** don't ship hour-of-day blocking standalone — n is too small and signal could be regime-specific. If we ever ship the [SMART_MAX_SIGMA gate](project_pm_btc_1h_killer_quadrant_2026_05_08.md), check whether it absorbs most of the hour-of-day signal (likely yes since high-sigma hours dominate the worst windows).

## Summary: total saves accounted for

Naive saves across rejected gates: +$251 (entry band) + $93-136 (chop/sigma/hour). All overlap heavily — they target the same trades from different angles. Replay validation collapses each to <$50 absolute.

The remaining un-tested candidate is **SMART_MAX_SIGMA** (see [killer quadrant memory](project_pm_btc_1h_killer_quadrant_2026_05_08.md)). It targets the cleanest fingerprint (entry≥0.66 × sigma≥0.0006 = 59% of loss) and uses an existing env var. That's the next sweep.
