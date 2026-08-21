# poolfarm-15m — 15m batch pairs. VERDICT: MARGINAL-NEGATIVE live; stopped by user 2026-08-13 ~16:10.

Code: `src/poolfarm.py`, `BAR_SECONDS=900`, BATCH quoting (PM_MM_BATCH_SH).
Yamls `chart/bots/{btc,eth}_poolfarm15m.yaml`. Paper from 13:10, btc LIVE
15:38–16:10 Kyiv 2026-08-13.

## Why 15m was attractive
Maker rebate ON (makerRebatesFeeShareBps=10000 — the bigger income piece:
$21.69 vs $4.67 on the 5m day), 96 bars/day = 4× the 1h pair cycles,
reward-eligible (minSize 50 / maxSpread 4.5¢). Open question was completion
physics (between 5m's 4% and 1h's 84%). Resolves on Chainlink TWAP-60
(NOT Binance — verified).

## What was implemented (this is where BATCH exec landed)
`PM_MM_BATCH_SH` (chart knob pmMmBatchSh): build the 50/50 in BATCH-share
maker increments; **imbalance throttle** — a side quotes only while
`inv(side) − inv(other) < BATCH` (max unhedged ≈ one batch); **cumulative
pair ceiling** — cap vs the opposite side's AVG cost so the aggregate pair
stays <0.985; venue min guards ($1 order, 5sh). Default BATCH=SIZE=50 ≡
one-shot. Deployed live with BATCH=10, band [0.30,0.70], quit 75s, warmup
10s, halt −$15, maxOrder $10.

## Timeline + results
- **Paper 13:10–15:37** (band [0.35,0.65]): ZERO fills across ~9 bars, both
  coins, in a violently trending afternoon (mids 0.86→0.06 bar-to-bar).
  Recorder analysis of the same hours: 104 deep sell prints / 6,498sh of
  fill opportunities existed, but ~75% occurred with mid OUTSIDE the band —
  the fair-zone gate was the binding constraint, plus paper's fill sim
  underestimates (no real queue position).
- **LIVE 15:38–16:10** (BATCH=10, band [0.30,0.70]): fills within minutes.
  Bar 15:30: 30up/20dn → matched 20/20 washed, 10sh residual lost → −$5.51.
  Bar 15:45: full 50/50 pair built in 10 batch fills → **+$2.50 (pair cost
  0.975)**. Bar 16:00: 10/0 building at stop. Ceiling visibly steered the
  2nd side (DOWN quoted exactly 0.985−0.59=0.39 after UP@0.59 filled).
  0 order errors; per-side cap held (max 50.0).
- **User verdict at 16:10: "this is not going to work" → stopped.** The mix
  (pair +$2.50 vs one-batch residual −$5.51) needs pairs ≥⅔ of filled bars
  to break even; nothing measured suggests that rate on 15m.

## Residual value
The 15m recorders (btc+eth mrec15m) keep running — the dataset supports any
future 15m question. The BATCH mechanics are proven live and generalize to
any duration (they were designed for this codebase, stay in poolfarm.py).
