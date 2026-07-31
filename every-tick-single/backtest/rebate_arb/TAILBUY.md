# Tail-buy at 1c on 5m bars — FAK study (2026-07-31)

Question (user): FAK-buy the dying side when it reaches 1c, hoping >1% of bars
revert. Data: rebate_arb cache (4,860 resolved markets, 27-30 Jul, 1Hz books +
all prints + ground truth). Post-close touches EXCLUDED (that is the separate,
known settlement-snipe edge); this is intrabar (tl>0) only.

## Headline — FAK version is -EV at every cap

| cap | touch events | win% | breakeven (incl taker fee) | EV c/share |
|---|---|---|---|---|
| ≤0.01 | 4,067 (84% of sides) | **0.52%** | 1.07% | **−0.55** |
| ≤0.02 | 4,196 | 1.02% | 2.14% | −0.82 |
| ≤0.03 | 4,298 | 1.68% | 3.20% | −0.98 |

Win rate is HALF of breakeven at 1c. The taker fee at p=0.01 (0.07·p(1−p) ≈
0.07c) is 7% of the stake and moves breakeven from 1.00→1.07%.

## Patterns — nothing survives

21 winners scattered over 4,067 events cannot support 40 buckets; every
"positive" cell is 2-8 of those 21 (the permutation-null trap from the
structure-hunt). Specifics:
- tl>120s (the only structurally sensible slice — early collapse, time to
  revert): 2 wins / 148 = 1.35% vs 1.6 expected at breakeven. Noise.
- hour=08 UTC "2.13%": 3 winners across 24 hour-buckets. Noise.
- coins: bnb 1.30% (8/615 vs 6.6 expected). Noise. doge 0/653.
- day-of-week: FOUR days of data (Mon-Thu). Mon 0/423, Wed 0.73%. No
  conclusion is possible; flagged for honesty, not evidence.
- volume/volatility terciles: 0.45-0.65%, no gradient.
- capacity if it worked: ~400sh typical at the touch = $4/event at 1c. Tiny.

## The reconciliation that matters — maker vs taker population

The deleted crash-catcher (git history; live logs archived in
data/archive/event-logs-2026-07-31/*-catcher/) ran the MAKER version of this
exact idea live: resting 1c/2c bids filled by panic SELL prints. Its real
record, 1,244 settles:

| fill px | n | live win% | breakeven (maker, no fee) | pnl |
|---|---|---|---|---|
| 0.01 | 505 | **1.39%** | 1.00% | +$6.51 |
| 0.02 | 739 | **2.30%** | 2.00% | +$0.75 |

Same tokens, same zone, OPPOSITE populations:
- a resting ASK at 1c = calm consensus that the side is dead → reverts 0.52%;
- a SELL PRINT smashed into a 1c bid = panic dump → reverts 1.4-2.3%.

The edge, to the extent it exists, belongs to the maker who buys FROM panic,
not the taker who buys from a calm seller. FAK is structurally the wrong side
of this trade, and no fee schedule fixes a 0.52%-vs-1.07% gap.

Even the maker version was only marginally +EV live (+$7.25 total at 5sh
across 1,244 settles ≈ +0.1c/share overall) — which is why it was killed.

## Verdict

Do not build the FAK tail-buyer. If the tail zone is ever revisited, it is the
maker catcher (already validated marginal-positive live, code in git history),
and the only lever worth testing is selective panic-quality filters on the
incoming print — not timing, hour, coin, or vol gates, none of which show
signal here.
