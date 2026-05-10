---
name: PM BTC 1h min-elapsed gate — sweep + reject 2026-05-08
description: 100-cell sweep tested SMART_MIN_ELAPSED_SECS / SMART_ENTRY_CEIL across 187h corpus. Both rejected — production (0.70, 0) had best absolute PnL. Don't re-litigate without a new motivating bundle.
type: project
---

**Status:** researched and rejected. Production stays at `(SMART_ENTRY_CEIL=0.70, SMART_MIN_ELAPSED_SECS=0)`.

**Motivation:** 19.9h bundle 20260507_091151 showed entries at ≥0.66 lost −$41.43 (12 trades) and first-10-min entries lost −$26.67 (8 trades). Hypothesis was tightening the entry-price ceiling and/or adding a min-elapsed gate would generalize.

**Sweep:** SMART_ENTRY_CEIL ∈ {0.62, 0.65, 0.68, 0.70} × SMART_MIN_ELAPSED_SECS ∈ {0, 300, 600, 900, 1200} on 5-bundle corpus (111h+22h+7h+26h+19.9h = 187h).

**Result table (top 5 by abs PnL):**

| CEIL | ELAPSED | Trades | PnL | ROI |
|------|---------|--------|---------|-------|
| 0.70 | 0 | 130 | +$213.68 | 10.7% ← prod |
| 0.70 | 600 | 97 | +$209.50 | 14.1% |
| 0.68 | 0 | 116 | +$194.36 | 11.2% |
| 0.70 | 300 | 116 | +$183.06 | 10.5% |
| 0.68 | 600 | 85 | +$181.70 | 14.3% |

**Why nothing shipped:**

1. **CEIL tightening is a clear loss.** 0.70 → 0.65 drops 53 trades and gives back $85 PnL across the corpus. The "entries ≥0.66 lose money" pattern was an artifact of the 19.9h bundle alone — did not generalize.

2. **MIN_ELAPSED=600 was a +ROI / −abs-PnL tradeoff.** Trims 130→97 trades, abs PnL −$4, ROI 10.7%→14.1%, fixes the only red bundle (26h: −$5→+$10). Initially shipped; rolled back same day — the $4 absolute hit and trade-count reduction wasn't worth it for a $3.4-pt ROI gain on replay (where the live slippage angle is speculative, not measured).

3. **MIN_ELAPSED in general had a softer signal than expected.** Going to 600 doesn't drop the worst trades — it drops a low-EV mix. So it's a capital-efficiency play, not a quality filter.

**How to apply:**

- Don't re-run this sweep without a *new* multi-bundle pattern. The 19.9h bundle hypothesis was thoroughly tested.
- When a single bundle motivates a tightening, sweep the corpus before shipping — n=20 trades on one bundle ≠ n=130 on five.
- The trade-3 disaster pattern (high-price entry + fragile thesis + reversal) is real but is NOT solvable by a static entry-price cap. Future leverage candidates: regime-aware sizing, peak-flat guard ported to 1h, or a per-bar position cap when |ret_30m| < threshold AND entry_price > 0.66 (compound condition, not just price).
