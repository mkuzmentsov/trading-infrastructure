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
- Distinct from the MAKER rebate. ⚠️ **CORRECTED 2026-09-07** — the maker rebate is
  **20% of the taker fee paid against YOUR OWN fills, NOT a pool split pro-rata**, and it
  is **NOT absent on 1h**: verified on four real payment days at exactly 20.0% of our own
  fee-equivalent (E7 2026-07-03, and 08-20/08-21 which were poolfarm-**1h** days).
  See [strat-rebate-farm-20260907](strat-rebate-farm-20260907.md) §0.

## ⭐ 2026-09-07 — the tier lever, costed against the live vacmaker (it is not a lever)
Our actual weighted volume is **$269/day ⇒ $8,065/30d ⇒ Bronze (3%)**, against a total taker
fee bill of **$6.13/day** (18.3% of the fleet's gross PnL in the calibrated replay):

| tier | 30d wV needed | × our volume | rebate | saving/day |
|---|---|---|---|---|
| Bronze (current) | 2,000 | — | 3% | **$0.18** |
| Silver | 20,000 | 2.5× | 8% | $0.49 |
| Gold | 200,000 | 24.8× | 18% | $1.10 |
| Platinum | 1,000,000 | 124× | 32% | $1.96 |
| Obsidian | 10,000,000 | **1,240×** | 50% | **$3.07** |

The fee bill caps the prize: even Obsidian saves $3.07/day. **Closed — the tier is not worth
one line of code.**

⭐ **The structural wrinkle that explains the incumbents.** `wV = shares × (1 − entry price) ×
2.3`, so cheap entries earn far more tier credit per share:

| band | % of our stake | **% of our weighted volume** | wV/share | fee/share |
|---|---|---|---|---|
| 0.55-0.75 | 5.7% | **53.5%** | 0.849 | 0.0161 |
| 0.75-0.90 | 8.9% | 26.2% | 0.361 | 0.0091 |
| 0.98-0.99 | **81.4%** | 17.9% | 0.031 | 0.0009 |

**The tier program pays for exactly the trades that are hardest to win** (27× the credit per
share in the cheap band vs the 0.99 grind). That is why an Obsidian settlement sniper paying
half fees can profitably take prices that are −EV for us: their cheap-entry volume buys the
tier that subsidises everything else. It steepens the moat; it does not open a door at our size.

## ⭐ 2026-09-07 — what maker execution would actually be worth to the vacmaker
The one profitable operation we have is a TAKER. Per the rebate_arb structural bound, the rebate
can only *subsidise an already-profitable maker operation* — so: what if the vacmaker's own
volume were executed as maker?

| | $/day |
|---|---|
| taker fee avoided | +6.13 (0.311 c/share) |
| maker rebate earned | +1.23 |
| **total swing** | **+7.36** on a current net of **$27.41/day (+27%)** |

That is larger than anything the rebate-farming lane offered — and it is unavailable: the queue
at the vacmaker's own fire prices is **17,391 shares at 0.98-0.99** and 10,974-19,502 shares at
tl 20-40. We cannot be the maker where we trade. Recorded so nobody re-derives the prize
without the constraint.

Fee formula (all crypto updown): taker-only, `fee = shares × 0.07 × p(1−p)`,
peaks 1.75¢/share at p=0.5; makers pay zero.
