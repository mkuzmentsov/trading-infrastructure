---
name: PM BTC 1h structural bleed diagnosis 2026-05-08
description: Live PnL across 187h corpus is −$363 (47% WR). The bot wins more often than it loses but loses 2.6× more per loss than per win — needs 72% WR to break even, has 55%. No knob retune fixes this; only blocking the worst-30 catastrophes can.
type: project
---

**Headline:** the bot is structurally negative-EV in current production. Not from a recent regime break — every 24h chunk of the 111h bundle is in the red.

## Numbers

Corpus: 271 closed trades, **−$363.52 live PnL**, 47% WR.

The 111h bundle dominates (197 / 271 trades) and tells the story:

```
Mean WIN:  +$1.77    Mean LOSS: −$4.55
Win/loss ratio: 0.39 → breakeven WR = 72%
Actual WR: 55% → bleed of $1.05/trade
```

## Where the bleed lives

| reason | n | WR | PnL | mean |
|---|---|---|---|---|
| late_bar_skim | 122 | 88% | +$182 | +$1.49 |
| thesis_break | 20 | 0% | −$127 | −$6.35 |
| late_bar_salvage | 35 | 0% | −$152 | −$4.33 |
| salvage_floor | 13 | 0% | −$87 | −$6.72 |
| salvage_velocity | 4 | 0% | −$21 | −$5.27 |

**52/197 trades (26%) hit a salvage path, all 0% WR, total −$260.** The skim engine almost offsets it (+$182). Bot is structurally a "win small often, lose big sometimes" machine.

## Loss concentration

- Worst 30 trades (15% of total): **−$215 — more than the entire loss**
- Other 167 trades net roughly break-even
- Top 10 winners: only +$41

## Why losses are structurally bigger than wins

Polymarket binary market mechanics, not a bot bug:

```
Entry @ 0.65, target 0.95-0.99: max upside +$0.34, max downside −$0.65
                                 → risk:reward 0.52
Entry @ 0.70:                   max upside +$0.30, max downside −$0.70
                                 → risk:reward 0.43
```

At any entry > 0.50 the payoff is asymmetric against us. Need high WR (≥72%) to compensate. We have 55%.

## What the corpus rules out

- **Knob retunes** (smartLateSkimBid, smartEntryCeil, smartMinElapsedSecs, peak_flat_max) each save <$30 corpus-wide vs the $363 bleed. Already proven on prior sweeps.
- **chop_ratio_30m alone** is not a clean discriminator. CHOP 3.0-5.0 bucket is actually a small winner (+$10). The 27h-bundle "CHOP fingerprint" was regime-specific clustering, not a generalizable rule.
- **Entry-price ceiling** does not fit cleanly: 0.50-0.62 entries are the WORST per-trade (mean −$2.02, 37% WR). 0.62-0.70 are roughly break-even. 0.70+ is mildly bad. So tightening CEIL hits good entries.

## How to apply

The only structural lever is **identifying and blocking the worst-30 catastrophe trades at entry time**. Look for entry-time features that predict salvage cases:
- Compound conditions (entry_price × sigma_5m × edge × book_divergence) likely beat single thresholds
- Worst trades cluster at extreme entries (<0.62 or >0.70)
- Direction asymmetry is regime-dependent, not structural (DOWN bled on 111h, UP bled on 27h)

Daily PnL was negative on **every single day** of the 111h window. Replay shows +$195 for the same period — gap to live (−$207) is ~$402, or ~$2/trade. That's the slippage tax + execution drag.

If no entry-time feature combination identifies most of the worst-30, then the bot is structurally negative-EV at current sizing/markets and the right move is fewer trades or different markets, not more knob tuning.
