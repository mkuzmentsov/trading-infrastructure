---
name: PM BTC 1h killer quadrant — high entry × high sigma 2026-05-08
description: 93 trades (34% of corpus) where entry≥0.66 AND sigma_5m≥0.0006 explain 59% of the corpus loss (−$170 of −$286). Cleanest single fingerprint we've found. SMART_MAX_SIGMA sweep is the proposed test.
type: project
---

**The cleanest catastrophe fingerprint identified so far:**

| entry | sigma_5m | n | PnL | mean |
|---|---|---|---|---|
| <0.66 | low (<0.0006) | 50 | −$20.62 | −$0.41 |
| <0.66 | high (≥0.0006) | 40 | −$24.48 | −$0.61 |
| ≥0.66 | low (<0.0006) | 64 | −$25.04 | −$0.39 |
| **≥0.66** | **high (≥0.0006)** | **93** | **−$170.05** | **−$1.83** ★ |

**93 of 271 trades (34%) generate 59% of the corpus loss.** Other three quadrants are roughly break-even per-trade.

## Why this fingerprint is real

Both factors have independent mechanistic stories:
- **High entry price** = thin upside (max gain $0.30 from 0.70 entry) vs full downside ($0.70 to 0)
- **High sigma_5m** = the volatility regime where the [fat-tail model](project_pm_btc_1h_fat_tail_model_2026_05_08.md) is most miscalibrated

Combined, you get the worst of both: a payoff structure that demands high WR to break even, and a regime where the model's WR predictions are most overconfident.

## Sigma_5m alone is also a strong signal

| sigma_5m | n | WR | PnL | Mean |
|---|---|---|---|---|
| <0.0004 | 61 | 52% | −$57 | −$0.94 |
| **0.0004-0.0006** | **73** | **62%** | **−$14** | **−$0.20** ← best |
| 0.0006-0.0008 | 67 | 57% | −$78 | −$1.16 |
| 0.0008-0.0010 | 36 | 50% | −$82 | **−$2.27** ← worst |
| >0.0010 | 34 | 47% | −$55 | −$1.61 |

Per-trade losses **double** above sigma=0.0008.

## Naive blocking results (replay TBD)

| Rule | Blocked | Block PnL | Naive Δ |
|---|---|---|---|
| **block sigma_5m > 0.0008** | **70** | **−$136** | **+$136** ★ |
| block sigma_5m > 0.0010 | 34 | −$55 | +$55 |
| block (sigma_5m > 0.0008 AND extreme p_up) | 62 | −$109 | +$109 |

## Implementation path

`SMART_MAX_SIGMA` env var already exists in `math_smart.py:228`:
```python
if SMART_MAX_SIGMA > 0 and ctx.sigma_5m > SMART_MAX_SIGMA:
    return _nope(f"Sigma too high {ctx.sigma_5m:.5f}")
```

Currently set to 0 (disabled). Single-knob change to test.

## Proposed sweep (NOT YET RUN)

`SMART_MAX_SIGMA ∈ {0.0006, 0.0007, 0.0008, 0.0009, 0.0010, 0.0012}` × prod baseline = 6 cells × 5 bundles = 30 runs (~6 min).

## Caveats

- **Naive savings overestimate replay savings.** Prior sweeps (entry-band, min-elapsed) showed the bot reroutes when preferred entries are blocked, which can cap or eliminate the benefit.
- **However**, this gate is different in nature: it skips an entire bar's entry-window (sigma persists across the bar), so the bot can't reroute to "the same trade at a slightly different time." The replay benefit should be closer to the naive number than for entry-price blocks.

## How to apply

If sigma_5m sweep validates: ship `SMART_MAX_SIGMA=0.0008` (or wherever the corpus optimum lands) as a single-knob production change. This is the highest-probability win we've identified that's still untested in replay. Run the sweep before shipping; check that no individual bundle regresses by more than $20 absolute.
