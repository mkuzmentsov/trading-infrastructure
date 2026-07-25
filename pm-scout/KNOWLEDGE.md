# pm-scout knowledge base

Living document. Read FULLY before every run. Append new findings at the bottom
of the relevant section after every run — this file is the module's memory.

## Fee & rebate model (verified 2026-07-22)
- **Crypto up/down (5m/15m/1h/daily) markets**: taker fee = `shares × 0.07 ×
  price × (1−price)` (peaks 1.75c/share at 50c). **Makers pay $0** and earn a
  daily rebate ≈ **20–25% of the counterparty's taker fee**.
- **Most event markets (politics/geo/sports/econ)**: fee-free both sides
  (pre-existing `feesEnabled=false` markets); check per-market fields.
- **Liquidity rewards program**: rewarded markets pay daily for resting
  two-sided quotes within `rewardsMaxSpread` of the mid with ≥ `rewardsMinSize`
  shares; weight peaks near 50c (`p(1−p)` shaped). Scanner surfaces
  rewards-carrying markets — free income on positions we'd hold anyway.

## Mechanics
- Min order 5 shares; tick 0.01; no dollar minimum (~$0.30 at 6c works).
- **Post-only GTC** exists: `engine/clob.py::place_limit_order` — exchange
  REJECTS a crossing order instead of taker-filling it. Use for all maker entries.
- Neg-risk events: multi-outcome, one resolves YES; NO-sweeps across all
  outcomes can exceed $1 payout — check `negRisk` flag.
- Resolution: UMA oracle or stated source. **ALWAYS read the resolution rules
  text before betting** — many "obvious" bets die on technical resolution terms
  (deadlines, sources, exact thresholds).
- Redemptions are NOT automatic — resolved winning positions must be claimed
  (`engine/redemptions.py`). Scan every run.

## Standing strategy verdicts (do not relitigate without new data)
- **Crypto UpDown 5m/15m: efficient-minus-spread** (2026-07-22 proof, 49k bars
  + 19h tick data): taker −EV at every price/time, maker −EV via adverse
  selection, no time-of-day/TA/vol pocket, no cross-asset lag, TP-scalps below
  martingale. NEVER bet these on price alone; only genuine external info could win.
- **Naive two-sided 50c quoting**: single-fill adverse selection dominates the
  +2c lock (needs >96% both-fill; real ≈90% paper-optimistic) — rebates don't
  close the gap. Mirror-maker btc-mm measured it live 2026-07-22.
- Longshot bias exists but is PRICED here (cheap tails win less than price).

## Scanner coverage (2026-07-22)
- `scan.py` does FULL-coverage sweeps: 5 global orderings (newest, 24h-volume,
  all-time-volume, liquidity, closing-soon) + per-category newest+volume passes
  for 11 high-level tags (Politics 2, Crypto 21, Sports 1, Business 107,
  Economy 100328, Geopolitics 100265, World 101970, Culture 596, Elections 144,
  Middle East 154, AI 439). Gamma caps pagination at ~2100 offset (422), so the
  multi-slice approach is what gets past it. Yields ~11.5k markets/run (was
  ~3k). Each record carries `cats` (matched high-level tags) for triage.

## Analysis doctrine
- Newest markets take precedence (early prices are least efficient; first
  liquidity is often lazy 50/50 or anchored wrong).
- Insider/whale flow is REAL signal on PM: enormous one-sided prints without
  public news often front-run announcements (flow.py detects). Follow smart
  entries cautiously; treat dumps against our side as close-warnings.
- Estimate probability FIRST (before looking hard at the price) to avoid
  anchoring; state confidence; only sizeable edge (≥5–10c after fees) is
  actionable given research uncertainty.
- **Resolution timing is part of every bet**: know WHEN each market resolves
  (endDate + resolution lag — sports settle in hours; UMA-disputed events can
  take days; econ markets settle on the announcement). Every bet line must show
  time-to-resolution and capital lock-up. At equal edge prefer the sooner
  resolution (capital recycles): compare bets on **edge per day locked**, not
  raw edge. A 3c edge resolving tomorrow beats 10c resolving in 3 months.
- Sizing: edge-and-confidence weighted, ≤20% of run bankroll per bet, keep
  ~20% reserve. Prefer maker entries (price improvement + rebates/rewards);
  taker only when the thesis is time-critical.
- If a position already exists in a market: never open an independent new bet —
  only HOLD / CLOSE / INCREASE via the portfolio-review section.

## Calibration ledger (append per resolved bet)
| date | market | side | entry | est.prob | outcome | pnl | lesson |
|------|--------|------|-------|----------|---------|-----|--------|

## Run log pointers
- Run records: `pm-scout/runs/run-<ts>.md`; orders: `pm-scout/runs/ledger.jsonl`.
