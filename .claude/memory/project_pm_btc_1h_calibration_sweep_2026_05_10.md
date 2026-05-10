---
name: PM BTC 1h calibration sweep 2026-05-10 — peak_flat=0.20 + shrink=0.80 shipped
description: 5-bundle sweep of SHRINKAGE×ZCAP (25 cells), peak_flat_max (5 cells), min_z_early (7 cells), and stacked combos. peak_flat=0.20 + shrink=0.80 wins all 5 bundles, +$90 vs prod (+65%). Shipped to overlay.
type: project
---

## What was swept (2026-05-10, 5 bundles: 111h/22h/7h/26.7h/76.2h)

### SHRINKAGE × PUP_Z_CAP (25 cells × 5 bundles = 125 runs)

**Key finding: SMART_PUP_Z_CAP has zero effect.** With MIN_Z_EARLY=2.2 setting the entry floor, clipping z at 2.0 or 1.5 doesn't change which trades fire — the edge remains above SMART_MIN_EDGE regardless. The knob only matters below ZC=1.2 where it starts cutting trades, and at that point it hurts joint PnL. **PUP_Z_CAP is the wrong abstraction; discard.**

SHRINKAGE alone does help:
```
SH=0.80  JOINT +$151.23  (vs prod SH=0.92: +$138.22 → +$13 gain)
SH=0.75  JOINT +$150.49
SH=0.85  JOINT +$142.93
SH=0.92  JOINT +$138.22  ← prod
```
Wins 3/5 bundles. Modest but consistent.

### peak_flat_max (5 cells × 5 bundles = 25 runs)

**Clear winner: peak_flat=0.20, wins ALL 5 bundles.**

```
peak_flat=0.20  JOINT +$217.79  (+$79.57 vs prod)  ← wins all 5
peak_flat=0.30  JOINT +$188.11
peak_flat=0.10  JOINT +$179.15
PROD (0.05)     JOINT +$138.22
```

Why: `peak_flat=0.05` gated out `salvage_floor` on virtually every 1h trade — any trade that peaked even 0.06 above entry was immune to salvage. Setting to 0.20 allows salvage on positions that peaked modestly then reversed. Deep-ITM positions (peak > 0.20 above entry) remain protected. The 26.7h bundle flips from −$4.91 → +$25.50, 76.2h from −$49.19 → −$20.97.

### Stacked: peak_flat=0.20 × SHRINKAGE

```
peak_flat=0.20 + shrink=0.80  JOINT +$228.68  (+$90.46 vs prod)  ← best, wins ALL 5
peak_flat=0.20 + shrink=0.85  JOINT +$222.50
peak_flat=0.20 standalone     JOINT +$217.79
peak_flat=0.20 + shrink=0.75  JOINT +$217.49
```

Per-bundle for the shipped config (peak_flat=0.20 + shrink=0.80):
```
111h:   +$190.30  vs prod +$170.90  (+$19.40)
22h:     +$18.49  vs prod  +$11.40   (+$7.09)
7h:      +$15.29  vs prod  +$10.02   (+$5.27)
26.7h:   +$24.60  vs prod   −$4.91  (+$29.51)  ← flips positive
76.2h:   −$20.00  vs prod  −$49.19  (+$29.19)  ← still negative but halved
```

### SMART_MIN_Z_EARLY sweep (7 cells × 5 bundles = 35 runs)

```
PROD (minZ=2.2)             JOINT +$138.22
peak_flat=0.20 + minZ=2.6   JOINT +$137.85  ← ~same as prod, but better recent bundles
minZ=2.6                    JOINT +$116.49
minZ=2.4                    JOINT  +$66.78
minZ=3.0                    JOINT  +$47.17
```

**Do NOT raise MIN_Z_EARLY.** While calibration shows z≥3 entries have 82.9% WR (profitable), the 111h bundle's skim engine runs on z=2.2–2.6 entries and generates +$170 in absolute PnL — cutting that wrecks the corpus. The "p_up 0.95+ is profitable" calibration finding is correct but the absolute dollar contribution of those higher-z trades doesn't compensate for what's lost.

### Empirical WR calibration (from all 5 bundle JSONL, 164 closed trades)

| p_up bucket | n | actual WR | avg entry breakeven | profitable? |
|---|---|---|---|---|
| [0.88,0.90) | 7 | 28.6% | ~67% | No — late-bar weak entries |
| [0.90,0.92) | 10 | 50.0% | ~67% | No |
| [0.92,0.95) | 112 | 61.6% | ~67% | Marginally no — bulk of trades |
| [0.95,1.01) | 35 | 82.9% | ~67% | **Yes — z≥3 entries are profitable** |

Mean PnL per bucket: [0.88-0.90) ≈ breakeven, [0.92-0.95) +$0.22/trade, [0.95-1.01) +$0.96/trade.

**Implication:** the model's highest-confidence tier is actually correct. But those trades are only 21% of corpus. The path to profitability is either concentrating on them (but at the cost of absolute PnL as min_z shows), or fixing the exit layer to cut losses on the 0.92-0.95 majority — which is what peak_flat=0.20 does.

## What shipped to `pm_btc_1h_smart.yaml`

```yaml
smartShrinkage: "0.80"                    # was default 0.92 (chart default)
smartSalvageRequirePeakFlatMax: "0.20"    # was 0.05
smartMaxSigma: "0"                        # unchanged — rejection confirmed
```

## How to apply

- Monitor next 30–50 live trades. Expected: fewer deep-hole losses (salvage_floor firing earlier on reversals). Live/replay gap on this change should be small since exit timing is what matters, not entry fills.
- After 50 trades, check: did the 26.7h pattern (reentry after salvage) repeat? If reentry block (900s) is still holding it, the gains should transfer to live.
- Don't revisit SMART_PUP_Z_CAP — it's the wrong lever.
- Don't raise SMART_MIN_Z_EARLY — costs more skim revenue than it saves in bleed.
- Remaining structural issue: 76.2h bundle is still −$20 in replay even with best config. The bleed continues at a slower rate.
