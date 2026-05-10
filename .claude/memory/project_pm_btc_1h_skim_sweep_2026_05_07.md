---
name: PM BTC 1h late-skim sweep null result 2026-05-07
description: 26-cell sweep of (SMART_LATE_SKIM_SECS, SMART_LATE_SKIM_BID) over 5 bundles confirmed production (1080, 0.99) is the global maximum; loosening either knob monotonically hurts.
type: project
---

5-bundle replay corpus (170h trading): 111.5h + 22.8h + 7.2h + 26.7h + 2.7h.
Grid: SECS ∈ {1080, 1500, 1800, 2100, 2400} × BID ∈ {0.82, 0.85, 0.88, 0.90, 0.92, 0.95, 0.99}.

**Top of leaderboard (joint PnL):**
- (1080, 0.99) +$195.96 ← production overlay
- (2100, 0.99) +$195.96 (identical — at 0.99 the gate barely fires, SECS irrelevant)
- (1080, 0.95) +$158.23 (−$37)
- (1080, 0.92) +$144.22 (−$52)
- (1080, 0.90) +$127.00 (−$69)
- (1080, 0.88) +$111.43 (−$84) ← chart default before overlay raised it

**Why:** The motivating trade was bundle 20260507_091151_2.7h trade 3 (UP @ 0.70, peaked at 0.86 UP_bid, late_bar_salvage at 0.36, −$10.88 live). User intuition was that a looser/earlier skim would have rescued it. Replay rejects this: peak was 0.86 (below even the 0.88 chart default), and across the full corpus every BID below 0.99 leaves money on the table from deep-ITM positions that resolve to ~1.00 at expiry. The 2.7h bundle is +$7-9 in replay across every config tested, so replay can't actually see the live trade-3 failure mode (replay-vs-live slippage gap).

**How to apply:** Don't tune late-skim further. The trade-3 anti-pattern (entry near 0.70 with BTC barely on-thesis side of bar_open, then BTC reverts and bid collapses) needs a different lever — entry-quality gate, peak-flat / drawdown-from-peak guard, or regime-aware salvage — not the skim threshold. When a single live loser tempts a knob retune, run the full 5-bundle replay before changing anything: this case was n=2 evidence that flipped on n=170h.