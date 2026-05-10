---
name: PM BTC 1h trade-23 peak-flat guard failure 2026-05-08
description: Trade 23 (May 8 3AM ET DOWN @ 0.67 → 0.04, −$21.43) was a textbook peak-flat-guard failure. Position peaked at 0.89 (peak−entry=0.22 > peak_flat_max=0.05), so salvage_floor was gated out. Replay confirms structural −$19.80 loss under all configs.
type: project
---

**The single worst trade in the corpus**, and the canonical example of why peak-flat guard is wrong on 1h bars.

## Trade anatomy

```
2026-05-08 3AM ET: DOWN @ 0.67, 34 shares, entry sl=3322 (~55 min left)
   BTC at entry: 79,429 (−$96 below bar_open 79,525) — DOWN correctly favored

  sl=2122 (35min): bid 0.89 ← PEAK (would have been +$7.49 if exited)
  sl=1822 (30min): bid 0.86, BTC drifting down further
  sl=1342 (22min): BTC crosses bar_open (+$11), bid 0.50
  sl=1138 (19min): BTC +$35, bid 0.40 ← salvage_floor threshold breached
  sl=1090 (18min): BTC +$68, bid 0.32
  sl= 536 ( 9min): bid 0.04, late_bar_salvage fires, exit −$21.43
```

## Why every guard failed

### `smartSalvageBidFloor=0.40` — blocked by peak-flat guard
```
peak_bid (0.89) − entry (0.67) = 0.22
smartSalvageRequirePeakFlatMax = 0.05
0.22 > 0.05 → salvage_floor GATED OUT
```
The peak-flat guard's design assumption (positions that peaked profitable rarely revert that far) is **false on 1h bars**. On 15m it held; on 1h with bigger move budgets, a 0.22 peak can fully revert.

### `smartThesisBreakSigmaMult=1.5` — threshold not breached when it mattered
At sl=1342 (BTC just crossed bar_open by $11), `|adverse_btc| = 0.00014` vs threshold `sigma_5m × 1.5 = 0.00068 × 1.5 = 0.00102`. By the time `|adverse_btc| > threshold` (~sl=1090), bid had already collapsed to 0.32 — too late.

### `late_bar_salvage` (smartSalvageSecs=540) — fired exactly when designed
9 min before bar end, bid=0.04 already. This gate is forced-exit catch-all, not damage control.

## Replay confirms structural loss

Ran `replay.py` on the bundle:
- **gates_on (current prod):** trade 23 is `expiry_loss`, **−$19.80**
- **gates_off (all 4 stops disabled):** same trade, **−$19.80**, same `expiry_loss`
- **Live:** `late_bar_salvage` @ 0.04, **−$21.43**

Replay-vs-live delta is only $1.63 (training data ends at sl=1090; replay marks expiry_loss using last-seen bid 0.32). **The trade is structurally a $19-21 loss under any current config we have.**

## How to apply

**Don't try to fix this trade in isolation by tightening peak_flat_max.** Two reasons:
1. The 15m peak-flat guard was validated *because* it protects winners that peaked profitable. Tightening it to 0.20 or 0.30 might re-introduce premature exits on the trades it was designed to save.
2. Trade 23 is one instance of a broader pattern (high-priced entry + fragile thesis + reversal) that's better attacked at the entry side via [killer quadrant](project_pm_btc_1h_killer_quadrant_2026_05_08.md) — block trades like this at entry rather than try to salvage mid-bar.

**Possible follow-ups if entry-side blocking doesn't work:**
- Drawdown-from-peak rule (not in the codebase yet): exit if `peak_bid − current_bid > 0.40`. Would have caught trade 23 around sl=1340 at bid 0.50, saving ~$15. Risk: trims winners that have a normal mid-bar dip then recover.
- Tighten `smartSalvageRequirePeakFlatMax` from 0.05 → 0.30. Allow salvage_floor when peak-entry is in 0.05-0.30 band. Trade 23 had 0.22 → would now allow salvage at sl=1138/bid 0.40, saving ~$12. Need replay sweep to confirm it doesn't break peak-then-recover winners.

## Pattern across the corpus

The "high-priced entry + BTC barely on thesis side + reversal" fingerprint shows up at least 5 times across recent bundles (trades labeled 3, 19, 23, 25, 26, 27 in earlier analyses). Each loses $10-21. They are the heart of the bleed and they're reproducible in replay → improvements can be tested deterministically.
