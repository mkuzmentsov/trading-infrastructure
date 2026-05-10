---
name: PM BTC 1h SMART_MAX_SIGMA — swept but NOT shipped, ultimately rejected 2026-05-10
description: 7-cell sweep on 5-bundle corpus showed +$48 (+28%). NOT shipped. Tested on 76.2h bundle (20260507_091151) 2026-05-10 — regresses −$21.89, blocking 3 profitable late_bar_skim winners. Two consecutive bundle regressions (27h −$18, 76.2h −$22). Gate shelved.
type: project
---

**Status: REJECTED. Do not ship.** `smartMaxSigma` stays at `"0"` in the overlay.

**Original sweep result (5-bundle corpus, 187h):** 7-cell sweep showed +$48 (+28%), 4/5 bundles win. Looked promising.

**Why rejected:** Tested on 76.2h bundle (20260507_091151_76.2h) on 2026-05-10:
- prod (MAX_SIGMA=0): 88 trades, −$49.19
- MAX_SIGMA=0.0010: 84 trades, −$71.08 → Δ = **−$21.89**

Gate blocked 3 profitable `late_bar_skim` trades (+$5.81, +$12.16, +$8.12) and only saved 1 loser (−$4.20). Same regression pattern as the 27h bundle (−$18). Two consecutive new-bundle regressions = gate doesn't generalize.

**Root cause of failure:** sigma_5m persists across a bar, but in trending regimes (recent market conditions) high sigma just means BTC is moving strongly *in the thesis direction* — those are the best late_bar_skim entries. The gate can't distinguish "high sigma because chaotic" from "high sigma because trending."

**Background:** [killer quadrant memory](project_pm_btc_1h_killer_quadrant_2026_05_08.md) identified 93 trades (entry≥0.66 AND sigma_5m≥0.0006) explaining 59% of corpus loss. Naive blocking analysis predicted +$136 saving. SMART_MAX_SIGMA was already plumbed (`math_smart.py:228`) but disabled in production.

## Sweep result

7 cells × 5 bundles = 35 replay runs. Production is `MAX_SIGMA=0` (disabled).

| MAX_SIGMA | Trades | WR | PnL | ROI | per-bundle (111h / 22h / 7h / 26h / 27h) |
|---|---|---|---|---|---|
| **0.0010** | 123 | **58.5%** | **+$217.58** | 11.5% | +196.36 / +28.32 / +19.62 / +8.84 / −35.56 |
| 0.0009 | 113 | 57.5% | +$196.78 | 11.4% | +172.28 / +20.20 / +17.77 / +25.30 / −38.77 |
| 0.0006 | 65 | 61.5% | +$193.13 | **+19.8%** | +176.24 / +8.73 / +14.07 / +23.79 / −29.70 |
| 0.0012 | 128 | 57.0% | +$191.96 | 9.6% | +165.13 / +22.62 / +19.62 / +7.99 / −23.40 |
| 0.0008 | 106 | 57.5% | +$182.12 | 11.4% | +164.02 / +11.80 / +17.77 / +14.45 / −25.92 |
| **DISABLED** | 137 | 55.5% | +$169.82 | 8.0% | +170.90 / +11.40 / +10.02 / **−4.91** / −17.59 ← prod |
| 0.0007 | 88 | 56.8% | +$157.32 | 11.8% | +178.79 / −13.64 / +13.19 / +2.30 / −23.32 |

## Why 0.0010

- **Best absolute PnL** (+$217.58, +$48 over prod)
- Wins 4/5 bundles individually (only 27h regresses −$18)
- Drops only 14 trades (137→123, 10%)
- ROI improves 8.0% → 11.5%, WR 55.5% → 58.5%
- 27h regression is within the live-vs-replay slippage band

`MAX_SIGMA=0.0006` is the ROI-max alternative (19.8% ROI) but ships fewer trades; not chosen because absolute PnL is lower.

## Why this worked when 4 prior sweeps didn't

Prior sweeps (skim, min-elapsed × ceil, entry-band, chop-ratio) all hit the same wall: blocking trades doesn't help because the bot reroutes to similar bad entries on the same bar. **Sigma is different — it persists across the entire bar.** When the sigma gate fires, the bot can't reroute to "the same trade at a slightly different time" because `sigma_5m > threshold` continues to be true.

This matches the prior prediction in killer-quadrant memory: "the replay benefit should be closer to the naive number than for entry-price blocks."

Naive prediction: +$136. Actual replay: +$48. Ratio: 35% — much higher than the ~5% recovery rate of prior sweeps.

## Mechanism (per fat-tail model memory)

High `sigma_5m` is the regime where the math model's Gaussian assumption fails worst. Real BTC moves are 3-4× implied σ on losers. The bot's z-score model overstates confidence by 30-45 pp at p_up extremes (where it makes 95% of bets). Blocking high-sigma entries removes the regime where the edge is most fictional.

## How to apply

- Confirm shipped via `./diff-config.sh pm-btc-1h-smart` after next `helm upgrade`
- Monitor: live PnL across the next 50-100 trades. If actual save is ≥$15, the gate is working as expected.
- Don't over-tune around 0.0010 yet. The 27h regression suggests further tightening (0.0009, 0.0008) is regime-specific. Keep at 0.0010 for now and gather 50+ post-deploy trades before any retune.
- This is the first successful sweep after 4 null-results. The pattern: gates targeting **persistent regime features** (sigma) work; gates targeting **bar-local features** (entry price, time) don't because the bot reroutes.
