# EXPERIMENTS — every-tick-single (recurring, run "time to time")

Working rules (same discipline as algo-trading-bot/experiments):
- Every experiment is a SIMULATION against the fleet's logged data (bar_snapshot +
  paper_bar_settle events) — no bot changes until a rule is ADOPTED.
- **Composition**: all sims run on the SAME position/snapshot dataset so deltas stack;
  before adopting anything, re-simulate the FULL candidate config (all adopted rules
  together) — rules that help alone can conflict jointly.
- Each run appends to the experiment's Runs log using the RUN RECORD format below —
  a result without its conditions is not evidence. Adoption also requires holding up
  on a fresh out-of-sample day.

**RUN RECORD format** (every run, no exceptions):
```
- <date> | data: <UTC window, n bars/positions/snapshots, coins> |
  regime mix: <chop/mid/trend % of bars in window> |
  baseline: <bot config + git commit of sim code> |
  params: <exact sim parameters> |
  result: <numbers> | verdict: ADOPT / REJECT / KEEP COLLECTING
```
Why each field: results here are strongly regime-dependent (same config: −$21/hr in
trend, +$36/hr in chop, 2026-07-03) — a result quoted without its regime mix is
meaningless; baseline config pins what delta was measured against; commit pins the
sim code so a rerun is reproducible.
- Data pull: `kubectl exec -n every-tick-single deploy/{coin}-every-tick-single -- cat
  /app/logs/logs-training-events.jsonl` per coin (context: `source .dev-env-source`).
  Join trap: settle's `market_start_ts` is the NEXT bar's; join snapshots↔settles on
  `condition_id == paper_condition_id`; settled bar start = floor(settle.ts/300)*300−300.

Current bot config (baseline all deltas measure against): one maker bid per bar per
coin at ENTRY_PRICE_CAP=0.48, alternate side, post-only-equivalent, no warmup, no
cutoff, TP 0.99, no stop, hold to expiry, $5/bar.

---

## E1 — Regime-gated entry: q(P | regime) grid  ⭐ decides go-live
**Question**: does quoting ONLY in chop-classified bars make the single-asset bot +EV,
and at which entry price P?
**Method**: per bar classify regime from PREV bars only (per-coin rolling p60/p85 of 5m
|move| — no lookahead); hypothetical fill at P if book ask crossed P (from snapshots);
q = win rate of those fills. Grid P ∈ [0.40..0.49].
**Decision**: GO if q(P|chop) − P ≥ +5pp at n ≥ 150 fills; gate must be implementable
at bar open. Charge the config for gate-lag bars (first trend bars misclassified).
**Runs**:
- 2026-07-03 | data: 11:00–12:00 UTC, 36 bars w/ snapshots, 4 coins | regime mix: trend-heavy
  (the day's worst hour) | baseline: alternate@0.48 hold-to-expiry, commit a6b1969 |
  params: P∈[0.40..0.49], fill=ask-crossed, no gate | result: all P negative ungated
  (best 0.40: −0.34/bar w/ cut); monotone deeper=better | verdict: KEEP COLLECTING
  (need chop-window grid before gating conclusion).

## E2 — Late-bar salvage sell
**Question**: when nearly dead late in the bar, does a resting maker sell salvage more
than it amputates comebacks?
**Method**: sim grid arm_secs × arm_below × salvage_price on positions with snapshot
series. Rule: at ≤arm_secs left, if held side's bid ≤ arm_below → rest sell at salvage.
**Decision**: ADOPT if delta > 0 with capped-wins ≈ 0 at n ≥ 300 positions.
**Runs**:
- 2026-07-03 | data: 11:07–14:30 UTC, 79 positions w/ snapshot series, 4 coins |
  regime mix: 1 trend hr + 2 chop hrs (fleet q 59.5% in window) | baseline:
  alternate@0.48 hold-to-expiry, commit a6b1969 | params: grid arm∈{60,90}s ×
  arm_below∈{.10,.15,.20,.30} × salvage∈{.20,.30,.50}; TP-exited positions excluded |
  result: best 90s/0.20/0.20 → +$6.32, 5 saved, 0 capped; arm 0.30 capped 4 wins
  → −$2.94 | verdict: KEEP COLLECTING (need n≥300, incl. trend-heavy windows).

## E3 — Early exit vs hold-to-expiry
**Question**: cut a losing position at T if unrecovered, or always hold? (Old finding:
7/7 deep dips recovered to WIN — holds may dominate; E2 may make this moot.)
**Method**: recovery curves from snapshots: P(win | bid ≤ x at t). Sim cut rules vs hold.
**Runs**: none yet.

## E4 — Side rule: alternate vs conviction vs prev-bar
**Question**: any side rule beat alternate? p_up is logged per bar since 2026-07-03.
**Method**: (a) conviction gate: trade only when |p_up−0.5| ≥ θ, measure calibration;
(b) prev-bar continuation/reversal (first pass on outcomes: 45.5% reversal = noise).
**Decision**: need calibration curve p_up→outcome monotone + edge ≥ +3pp over alternate.
**Runs**:
- 2026-07-03 | data: full day, 121 consecutive-bar pairs, 4 coins | regime mix: full
  cycle (morning chop, midday trend, afternoon chop) | baseline: n/a (outcome-only) |
  params: P(flip vs prev outcome) | result: 45.5% ±4.5 = noise | verdict: REJECT
  prev-bar rules on outcomes; conviction gate KEEP COLLECTING (p_up logging began 11:00 UTC).

## E5 — Book-imbalance toxicity filter (Glosten-Milgrom)
**Question**: do fills taken when the book is lopsided (thin opposite side, big
bid/ask size skew) lose more? Can we skip quoting then?
**Method**: from snapshots at/before fill time: imbalance = (bid_size−ask_size)/(sum);
bucket fill outcomes by imbalance; sim "quote only when |imbalance| < θ".
**Runs**: none yet (snapshot sizes logged since 2026-07-03 ~11:00 UTC).

## E6 — Session/time-of-day gate
**Question**: are some UTC hours structurally chop (Asia) vs trend (EU/US opens)?
Cheap complement to E1 (calendar prior vs realized-vol gate).
**Method**: q and PnL by UTC hour across ≥1 week; compare E1-gate vs hour-gate vs both.
**Runs**:
- 2026-07-03 | data: 06:00–14:00 UTC hourly PnL, live btc + paper fleet | regime mix:
  is the measurement | baseline: mixed (live two-sided + paper single) | params: none |
  result: 07:00 chop (+), 10:00–11:30 trend (−), 12:00–13:00 chop (+) | verdict:
  KEEP COLLECTING (need ≥1 week for calendar prior).

## E7 — Realized rebate measurement
**Question**: what did the live day actually earn in nightly pUSD rebates vs the
fee_equivalent weights we logged? Calibrates the rebate term in all EV math.
**Method**: check the live account (proxy 0xD632…1b2F) for the pUSD credit from
2026-07-03's ~90 filled maker orders; divide by logged fee_eq sum.
**Runs**: pending first payout (due ~2026-07-04 morning).

## E8 — Coin selection
**Question**: is eth/sol outperformance persistent (less informed 5m flow) or drift?
**Method**: per-coin q with confidence bands, weekly; drop/add coins only at n ≥ 300.
**Runs**: 2026-07-03: eth 70%/sol 72% vs btc 48%/xrp 47% — one afternoon, no verdict.
