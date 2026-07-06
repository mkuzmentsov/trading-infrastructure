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
- 2026-07-03 | data: 06:00–14:45 UTC, 184 settled bars w/ snapshots, 4 coins | regime
  mix: chop-heavy by trailing classification | baseline: sim commit (backtest/sim.py v1) |
  params: NO-LOOKAHEAD gate (bar t classified by |ret(t-1)| vs trailing-36 p60/p85),
  fill proxy = ask crossed P, both sides counted | result: **negative at ALL (P, regime)**
  — q(0.48|chop)=37.1% (n=175) vs 48% needed; best cell trend/0.44 EV −0.049 |
  ⚠ METHOD FINDING: proxy fills q=37% vs the bot's REALIZED fills q=52% same window —
  ask-crossed overcounts toxic moments and the prev-bar gate is far weaker than the
  same-hour (lookahead) classification used in earlier eyeball analysis. NEXT: add
  trade_print logging (exact fills) and re-test; also test one-side-per-bar sampling
  to match the real bot. | verdict: KEEP COLLECTING (proxy inadequate, do not conclude).
- 2026-07-04 | data: 00:00–05:15 UTC (overnight Asia), 256 bars ALL with trade prints,
  4 coins, 200ms-tick fleet | regime mix: chop-heavy overnight | baseline: alternate@0.48,
  fleet realized q=41.6% pnl −99.19 in window | params: PRINT-EXACT fills (bid at P fills
  iff print ≤ P), no-lookahead trailing-36 gate, P∈[0.40..0.49] | result: **negative at
  ALL 18 (P, regime) cells** — best cell mid/0.44 EV −0.023; q(0.48|chop)=40.2% (n=256)
  vs 48% needed. Combined with 2026-07-03 full day (q=50.9%, +47.52): two-day realized
  q ≈ 47-48% ≈ exactly breakeven BEFORE adverse nights like this one. | verdict:
  E1 GO criterion (+5pp) is FAILING with exact fills. One more full-day cycle to
  confirm, then E1 → REJECT unless the rebate calibration (E7) changes the math.

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
- 2026-07-03 | data: 06:00–14:45 UTC, 121 positions, 4 coins | regime mix: full-day |
  baseline: alternate@0.48 hold-to-expiry (pnl +6.61), sim backtest/sim.py v1 |
  params: 90s / bid≤0.20 / sell@0.20 | result: delta +2.61 (9 saved, 2 CAPPED wins —
  knife edge is real) | verdict: KEEP COLLECTING (capped>0 fails the ≈0 rule; retest
  with trade_print fills at n≥300).

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
**Runs**:
- 2026-07-04 | data: MAKER_REBATE credit +$3.327 at 00:45 UTC for 2026-07-03's live
  maker fills (164 trades, ~1312 shares, fee_eq sum $16.93) | regime mix: n/a |
  baseline: live two-sided day | params: none | result: **capture = exactly 20.0% of
  OWN fee-equivalent** (= rebateRate, no pool dilution observed) → calibrated constant:
  rebate/share = 0.2 × 0.07 × p(1−p) ≈ 0.35c/share at ~50c fills → breakeven-q shift
  ≈ +0.35pp only. Does NOT bridge E1's ~8pp gap. | verdict: CALIBRATED (use
  0.014·p(1−p) $/share in all EV math; retest capture if fill volume grows 10x).

## E8 — Coin selection
**Question**: is eth/sol outperformance persistent (less informed 5m flow) or drift?
**Method**: per-coin q with confidence bands, weekly; drop/add coins only at n ≥ 300.
**Runs**: 2026-07-03: eth 70%/sol 72% vs btc 48%/xrp 47% — one afternoon, no verdict.


---

# ROADMAP — experiments unlocked as data accumulates

## Tier A — after ~3 full days (print-exact)
- **A1 composite config sim**: best-per-experiment rules combined (gate + salvage +
  side rule) re-simulated jointly per the composition rule — THE go/no-go artifact.
- **A2 print-flow regime signal**: print RATE and aggressor imbalance (BUY vs SELL
  prints) in the first 30-60s of a bar as a same-bar gate — faster than prev-bar
  klines, purely implementable at quote time. Compare vs E1 trailing gate.
- **A3 time-of-fill conditioning (print-exact)**: q by fill second within bar; if
  early fills are less toxic, quote only a window (revisits the old chase-era finding
  with exact fills).
- **A4 TP level grid**: TP 0.99 vs 0.90/0.80/0.70 vs none — prints tell exactly which
  TPs fill; maybe harvesting partial wins beats holding for 1.00.
- **A5 deep two-sided revisit**: 0.40-0.44 pair pricing + fast cuts (the deleted
  both-project's most promising direction) simulated print-exact — pairs = both sides
  print through P; requires modeling both legs.

## Tier B — after ~1 week
- **B1 cross-coin lead-lag**: do btc prints/moves lead alt bar outcomes by seconds?
  If yes: quote alts using btc order flow (the only genuinely predictive signal
  candidate we have not measured).
- **B2 queue/competition model**: our fill share vs printed size per level (thin xrp
  vs thick btc); calibrates paper optimism per coin, feeds E8 coin selection verdict.
- **B3 large-print toxicity**: does an unusually large aggressive print predict
  continuation? If yes: pull the resting quote on big prints (GM in its purest form).
- **B4 calendar structure**: day-of-week x hour heatmap of q; weekend regime; US data
  release minutes blacklist.
- **B5 p_up calibration** (E4 continuation): enough bars to fit calibration curve;
  conviction-gated single-side sim.

## Tier C — after ~1 month / only if some config is +EV
- **C1 Kelly sizing** on the measured edge distribution (risk-of-ruin bankroll calc
  like the algo-trader leverage frontier).
- **C2 size laddering**: multiple resting levels (0.48 + 0.44 + 0.40) as one book;
  per-level q from prints already measurable, joint inventory needs sim work.
- **C3 rebate-aware volume config**: if capture stays 20% of own fee_eq, optimal
  volume maximization at breakeven-q configs (rebate as the only profit) — check
  whether 20% holds at 10x volume first (E7 retest).
- **C4 live pilot**: smallest size, one coin, only after A1 composite is +EV on
  >=1 week AND an out-of-sample day; per-bot budget + own-orders-only cancels
  (multi-bot account safety from PLAN).


---

# RESEARCH PROGRAM — discipline-based experiments (from 2026-07-06, with ≥3 days of print data)

All experiments follow the RUN RECORD format; nothing is adopted without the joint
composite re-sim AND the ST-4 multiple-testing haircut. Sequencing at the bottom.

## I. Market microstructure (highest priority)
- **MS-1 order-flow imbalance gate** (Glosten-Milgrom/O'Hara): aggressor ratio of first
  30-60s of prints predicts the bar, available AT QUOTE TIME. Sim "quote only when
  balanced". GO: gated q − ungated ≥ +4pp, n≥200.
- **MS-2 book-pressure toxicity** (VPIN-flavored; supersedes E5): bid/ask size ratios
  from snapshots → same GO.
- **MS-3 large-print pull rule**: one big aggressive print → pull quote N secs.
  GO: avoided fills have q < 40%.
- **MS-4 implied vs realized vol ⭐ highest-conviction**: binary price = digital
  option; fair p_up from Binance realized vol vs market mid; trade only
  |divergence| > θ as TAKER (sidesteps maker adverse selection entirely).
  GO: net +EV after 7% taker fee schedule on ≥1wk sim.
- **MS-5 resolution-source divergence**: Chainlink (resolution) vs trading flow near
  bar end; measure mispricing episodes in final 30s before considering latency play.

## II. Betting & gambling theory
- **BB-1 Kelly / risk-of-ruin** (Thorp; Chen & Ankenman): for any +EV config —
  fractional Kelly + bankroll for <1% ruin (algo-trader leverage-frontier method).
  Blocks live sizing.
- **BB-2 CLV standing metric** (Wong): fill price vs bar-end price in every sim
  output; fast edge-quality signal. DO FIRST (cheap).
- **BB-3 dutching / middles**: after one leg fills, bid the other wherever pair-sum
  < 0.95 → locked middle. Print-exact simulatable.
- **BB-4 game selection formalized** (poker): coins × hours × regimes where q clears
  breakeven; refuse everything else. Umbrella over all gates (grows E6/E8).

## III. Statistics & econometrics
- **ST-1 calibrated outcome model** (backtest/ml_outcome.py; needs sklearn venv):
  logistic + GBM, TIME-ORDERED walk-forward (train earlier→test later, no shuffle),
  Brier/AUC vs coin-flip. Two feature sets: PRE-BAR (at open = true forecast) and
  EARLY-BAR (~60s in). **Runs:**
  - 2026-07-05 | 2146 bars, 3 days, 60/40 time split (train 1287 / test 859) | result:
    PRE-BAR features AUC 0.518, Brier 0.252 = NO edge (worse than coin flip) → outcome
    UNPREDICTABLE at bar open. EARLY-BAR AUC 0.691 "beats coin flip" BUT attribution
    shows it is ENTIRELY the price-move feature (moveonly AUC 0.691; flowonly 0.523 ≈
    nothing) — i.e. the model reads the current mid, which is already priced (momentum_
    taker proved q≈ask there). The ML CONFIRMS efficiency, does not break it. | verdict:
    NO FORECASTABLE EDGE. Only "signal" is the current price, which is efficient. Re-run
    at ≥1-2 weeks; add MS-5 resolution-source features (the one unpriced candidate)
    before concluding permanently.
  - 2026-07-05b | same 3 days, current-price feature REMOVED, "hist" set = last 12
    bars OHLC (intrabar returns + gaps) + vol + hour, NO current-bar info | result:
    AUC 0.530, Brier 0.250-0.254 (logreg/gbm) — indistinguishable from a coin flip and
    WORSE than predict-base-rate (Brier 0.249). Pure price history does NOT forecast the
    next 5m outcome. | verdict: **5m bar direction is a martingale** — unpredictable from
    history OR same-bar priced info. Direction-prediction is dead pending (a) much more
    data and (b) MS-5 resolution-source (Chainlink-vs-Binance) features, the only
    unpriced candidate left. Re-run: mlvenv python backtest/ml_outcome.py <dates>.
- **ST-2 HMM regime model** (Hamilton): 2-3 state HMM on 5m |ret| — persistence
  built in (what the trailing-percentile gate lacked). GO: beats E1 gate.
- **ST-3 edge-decay CUSUM**: rolling edge + changepoint detection on every adopted
  rule; data retires rules, not losses.
- **ST-4 multiple-testing haircut** (White's Reality Check / DSR): family-wide
  correction over the whole config grid. GATE FOR ANY LIVE PILOT.
- **ST-5 block-bootstrap CIs**: hour-block resampled PnL confidence intervals in
  every run record.

## IV. Technical analysis (low prior, cheap)
- **TA-1 mean-reversion / lag-1,2,3 direction+magnitude** (backtest/reversion.py). **Runs:**
  - 2026-07-06 | data: 62d/72k Binance bars + 3d paper | result: REAL short-term
    mean-reversion, MONOTONIC in prior-move size — P(continue) 0.500 (<5bps) → 0.484
    (5-15) → 0.464 (>15bps); on OUR paper bars reversion win rate 0.543(>10) → 0.547(>15)
    → 0.556(>20) → 0.574(>30bps); OOS lag-1/2/3 model AUC 0.52. Signal is genuine and
    corroborated (documented overreaction + Binance OOS + paper agree). BUT PRICED: the
    reversion side OPENS at avg ask 0.529 ≈ the 0.547 win rate → taker entry EV +0.0005/sh
    (break-even, neg after fee); maker rest@0.48 fills only the adversely-selected losing
    subset (q collapses to 0.466). | verdict: SIGNAL REAL BUT PRICED — efficiency to within
    the fee, third confirmation. Not exploitable maker or taker. Re-run with more data; the
    only edge would need a FASTER read of the move than the market (latency), i.e. MS-5.
- **TA-1b/2/3/4 technical indicators** (backtest/ml_technical.py). **Runs:**
  - 2026-07-06 | data: 72k Binance bars (RSI, Boll %B, MACD, Stoch, ATR, ROC, SMA-dist,
    streak, candle body/wicks — 12 indicators, all prior-bar, no lookahead) | result:
    OUTCOME prediction AUC 0.527 logreg / 0.533 gbm (same ~0.53 ceiling as raw lags);
    confident preds beat 50c ON OUTCOME (|p-.5|>.05 → 54.6% win). **DECISIVE combined
    test** (train TA on Binance < 2026-07-03, apply to paper bars, place MAKER bid at P
    on predicted side, print-exact fill): win% 46.2% @0.50 all preds → EV −0.035/sh;
    and CONFIDENCE INVERTS IT — at |p-.5|≥0.10 the filled win rate DROPS to 29.6%
    (not rises). Reason: the model is confident when price moved; those bars price the
    move, so a maker bid only fills when the market REVERSES against the prediction —
    the fill selects the wrong-prediction subset. The 54% outcome edge becomes 30%
    realized. | verdict: TA + maker placement NEGATIVE at every price/confidence; the
    better the signal, the worse the maker fill adversely selects. Fourth confirmation
    of the wall, and the sharpest: signal quality cannot survive the fill mechanism.
- **TA-2 round-number magnets**: BTC near round levels → chop-probability feature.
- **TA-3 volume-spike trend filter**: 1m volume z at open → skip bar.
- **TA-4 ATR-adaptive entry depth**: P as function of current ATR instead of fixed.

## V. Crypto-specific
- **CR-1 funding-rate drift prior** (via trading-mcp data) → slow side prior.
- **CR-2 liquidation-cascade detector**: extreme 1m bar → gate off (forced-flow
  continuation).
- **CR-3 calendar structure**: dow × hour heatmaps at ≥2 weeks.

## PRELIMINARY RUNS (2026-07-05, backtest/experiments.py, 3 days: Jul 3 full + Jul 4 full + Jul 5 partial)
Prototyped early so the harness is ready; RE-RUN with >=1 week + ST-4 haircut before any conclusion.

- **BB-2 CLV** | data: 3 days, 271+501+583 positions | result: mean CLV = +0.001 /
  -0.019 / -0.029 (t = 0.0 / -1.0 / -1.7); held-side final mid - entry | verdict:
  CONFIRMS NO MAKER EDGE — CLV at-or-below zero every day, trending negative. Fast-
  converging proof that resting-maker fills have no positive edge, matching E1. KEEP
  as a standing metric in every future sim.

- **MS-1 order-flow gate** (FIRST CONSISTENT SIGNAL) | data: 3 days | method: cross-token
  directional flow (UP-vol - DOWN-vol)/total in first 60s, bucket fill q by
  with/against our side | result: with-flow q BEATS against-flow ALL 3 days:
  0.535 vs 0.467 (Jul3, +6.8pp), 0.481 vs 0.454 (Jul4, +2.7), 0.475 vs 0.456
  (Jul5, +1.9); pooled ~+3-4pp, sign stable | verdict: PROMISING — early order flow
  has predictive content (only signal found with a consistent sign). NOT yet a
  standalone winner (with-flow q ~0.48 ≈ breakeven). NEXT: use as SIDE-PICKER (bid the
  flow side vs alternate) + as gate (skip when flow disagrees); re-run n>=1000 with
  block-bootstrap CI (ST-5); put in the composite. Lead to develop.

- **MS-4 implied-vs-realized (taker fade)** | data: 3 days | method: crude v1 — fade
  market deviation from 0.5 beyond theta=0.05, buy underpriced side at ask as taker
  (7% fee) | result: +0.154 / -0.061 / +0.015 $/share (q 0.569/0.375/0.443) — huge
  regime variance, pooled ~flat | verdict: INCONCLUSIVE, v1 too crude. Rebuild with
  proper realized-vol fair p_up before judging; still the best structural idea.

## FOLLOW-UP RUNS (2026-07-05 — chase MS-1, test momentum + streaks) — a clean efficiency result

- **MS-1 as SIDE-PICKER (downgrade)** | pooled n=2138 | flow-pick q = 0.524 vs
  base-UP rate 0.525 → picking the early-flow side is NO better than always-UP
  (crypto up-drift). The earlier "with-flow beats against-flow +3-4pp" was real but
  OVERLAPS the up-drift, not additive. MS-1 demoted: keep only as a possible gate,
  not a side edge.

- **MOMENTUM continuation is REAL but PRICED (the key finding)** | pooled n≈2000 |
  bars TREND intra-bar: continuation q rises 0.61 (30s) → 0.67 (60s) → 0.775 (120s).
  BUT traded as taker (buy moved side at its ask), q ≈ avg_ask_paid at EVERY threshold
  (60s: q0.67/ask0.667; 120s: q0.749/ask0.744) → edge before fee ≈ 0, and the 7% taker
  fee makes it net −0.002 to −0.03 $/share EVERYWHERE. The market has already priced
  the continuation into the ask. | verdict: MOMENTUM NOT EXPLOITABLE — market efficient
  to within the fee. This closes MS-4's momentum variant too: the maker side loses to
  adverse selection, the taker side loses to efficient pricing + fee. Same wall from
  both directions.

- **LOSS CLUSTERING (only actionable output)** | pooled n=1355 | P(fill loses | prev
  fill lost) = 0.659 vs base loss 0.534 → losses cluster hard (regime persistence).
  A "stop quoting for the rest of the hour after N consecutive losses" gate would dodge
  the worst streaks. Doesn't CREATE edge but cuts drawdown/variance — matters only IF a
  breakeven-rebate-farming config exists. | verdict: KEEP for the composite as a
  risk/variance gate, not an edge source.

**Session synthesis**: these 5m binaries are priced efficiently to within the taker
fee. Maker resting loses to adverse selection (q<breakeven); taker momentum loses to
already-adjusted asks + fee (q≈ask). CLV ≈ 0. No directional edge found in 3 days of
print-exact data. Remaining live hopes: (a) rebate-farming AT breakeven (needs a gate
that lifts q to ~0.48 while keeping volume — MS-1-gate + loss-streak-gate + regime),
(b) MS-5 resolution-source (Chainlink vs Binance) divergence in the final seconds —
the one angle untested and the only place a latency/data edge could still hide.

## ⭐ PRE-OPEN RESTING HYPOTHESIS (2026-07-06, user idea) — FIRST non-negative result
The next 5m market is live + liquid (50-80k sh/side) DURING the current bar. Pre-open
there is NO realized move to be informed about (the bar open isn't set), so fills there
should be unbiased. backtest/preopen_study.py, 120 resolved btc markets, 1-min mid proxy:
```
   P     PRE-OPEN win%   INTRA-BAR win%   pre edge(win-P)
 0.48    45.9% (n37)     38.6% (n176)     -0.021
 0.49    44.8% (n67)     40.0% (n185)     -0.042
 0.50    50.9% (n163)    41.5% (n195)     +0.009
```
FINDING: pre-open fills are ~7-9pp LESS adversely selected than intra-bar at every price
— the ONLY place the ~4pp adverse-selection gap closes. At 0.50, pre-open win 50.9% is
ABOVE breakeven (+0.009 on outcome, before rebate). This is qualitatively different from
every other result (all ~4pp below price). HEAVY CAVEATS: (1) 1-min MID proxy, not trade
prints — overstates fills, ignores queue position (a 0.50 bid sits behind ~50k sh); (2)
n=120 mkts ≈ 10h; (3) +0.009 within noise. VERDICT: PROMISING, needs print-exact test.
NEXT (decisive): instrument the bot to also track the next 1-3 future markets' prints+book
during the current bar (log preopen_print/preopen_snapshot tagged with target window),
then measure real pre-open fill rate + win rate + queue. If ~breakeven holds print-exact,
rebate-farming on unbiased pre-open fills = first viable config. THE lead to pursue.

## Sequencing
- **Week 1** (≥3 days prints): BB-2, MS-1, MS-2, ST-5 + Tier-A composite (A1).
- **Week 2**: MS-4 ⭐, ST-1, ST-2, BB-3.
- **Week 3+**: TA/CR block, ST-4 haircut over everything, then BB-1 sizing if
  anything survives.
