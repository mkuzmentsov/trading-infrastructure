# Venue taker-rebate program (facts). VERDICT for us: scale-gated, irrelevant at current bankroll.

Researched 2026-08-13 (docs + press). Launched 2026-05-29. Tiers on ROLLING
30-DAY WEIGHTED volume, paid DAILY in pUSD:

| tier | 30d weighted vol | rebate | level-up bonus |
|---|---|---|---|
| Bronze | $2,000 | 3% | $10 |
| Silver | $20,000 | 8% | $50 |
| Gold | $200,000 | 18% | $250 |
| Platinum | $1,000,000 | 32% | $1,500 |
| Diamond | $4,000,000 | 44% | $7,500 |
| Obsidian | $10,000,000+ | 50% | $25,000 |

Weighted volume: `wV = trade size × (1 − entry price) × category weight ×
bonuses`; **crypto markets weight 2.3×**, cheap entries weigh more;
Geopolitics earns 0 wV.

Implications:
- At ~$90 cycling we are Bronze at best: 3% of the 0.07·p(1−p) fee ≈
  0.05¢/share at mid — noise. Gold needs ≈$3-7k/day of taker spend for 30d.
- The program SUBSIDIZES the incumbent taker fleets: an Obsidian settlement
  sniper pays HALF fees — that is why they can profitably take prices that
  are −EV for us. It steepens the moat; it does not open a door at our size.
- Distinct from the MAKER rebate (20% of taker fees to makers pro-rata,
  makerRebatesFeeShareBps=10000 on 5m/15m; ABSENT on 1h/1d).

Fee formula (all crypto updown): taker-only, `fee = shares × 0.07 × p(1−p)`,
peaks 1.75¢/share at p=0.5; makers pay zero.
