---
name: PM BTC 1h SMART_CALIB_ALPHA sweep — rejected 2026-05-11
description: Alpha-blend calibration sweep (0–1.0) on 5 bundles with shrink=0.80+peak_flat=0.20 baseline. Monotonically hurts joint PnL; baseline wins at +$227. Code wired but disabled by default.
type: project
---

## What was tested (2026-05-11, 5 bundles: 111h/22.8h/7.2h/26.7h/83.4h)

Alpha-blend calibration: `p_up = (1-alpha)*model_p_up + alpha*empirical_wr`
- `empirical_wr = 0.829 if abs(z) >= 3.0 else 0.616`
- Env var: `SMART_CALIB_ALPHA`
- Baseline: `shrink=0.80 + peak_flat=0.20`

## Results

```
Config          111h    22.8h    7.2h   26.7h   83.4h    JOINT
BASELINE      $+190.30  $+18.49  $+15.29  $+24.60  $-21.16  $+227.52  ← wins
alpha=0.25    $+141.62   $+6.78  $+10.66   $+4.16  $-14.12  $+149.10
alpha=0.50     $+87.72  $+11.42  $+11.59   $-0.81  $-11.28   $+98.64
alpha=0.75     $+28.47   $+7.85  $+14.75   $-9.65  $-11.25   $+30.17
alpha=1.00      $+0.30  $+15.05   $+6.73   $-7.32  $-23.95    $-9.19
```

**Decision: REJECTED. Do not set SMART_CALIB_ALPHA > 0.**

## Why it fails

The 111h bundle dominates joint PnL (~85% of total). It relies on the skim engine
firing on z≥2.2 entries (which have actual WR ~62%, below 67% breakeven). However
those entries are profitable in aggregate because the skim exit captures 0.93-0.99
bids on markets that would resolve at 1.0 — the upside capture more than compensates.

Blending p_up toward 0.616 drags these trades' edge below MIN_EDGE=0.03, killing the
skim revenue entirely. The 111h bundle drops from +$190 → +$0 at alpha=1.0.

## What's wired

`SMART_CALIB_ALPHA` env var added to `math_smart.py` (after shrinkage step). Default
is `"0"` which disables it. Code path:
```python
if SMART_CALIB_ALPHA > 0:
    empirical_wr = 0.829 if abs(z) >= 3.0 else 0.616
    p_up = (1.0 - SMART_CALIB_ALPHA) * p_up + SMART_CALIB_ALPHA * empirical_wr
    p_up = _clip(p_up, 0.05, 0.95)
```

## How to apply

- Never set SMART_CALIB_ALPHA > 0 without a new corpus that changes the 111h regime finding.
- The [0.92-0.95) bucket bleed is real, but fixing it via calibration destroys skim revenue.
- The correct lever is already in production: peak_flat=0.20 cuts losses on reversals in that bucket.
- If a future regime makes skim-engine revenue negligible, revisit calibration at that point.
