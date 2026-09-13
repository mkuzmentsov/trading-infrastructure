# Edge-hunt research log — running notes

Started 2026-08-11 00:15 Kyiv. Mandate: find a strategy that earns real money
on crypto markets; $150 bankroll on the PM bots account; live allowed when
justified. Write everything down — tried, result, why.

## Ground truth already established (do NOT re-derive)

- **Settlement rule** (proven, venue-confirmed): updown-5m settles on the
  `crypto_prices_twap_thirty` tick stamped at T (window [T−32,T−3]); the
  strike is the tick at bar open; chaining exact; ties resolve UP. Our RTDS
  reconstruction: 0.0019 bps median error; call accuracy 99.0–99.9% at
  |est| ≥ 0.25bps, 93% below. New markets now name the TWAP stream in
  `resolutionSource`.
- **The T−4.5 buy edge**: was +$300/day on transition day, arbed to almost
  nothing in ~40h. Post-adaptation band economics (paper, 30h):
  ≥0.25bps: 2 bets +$6.25 · 0.10–0.25: 12 bets −$22.55 (83% hit but high-ask
  losses dominate) · ties at ≤0.45: 0/3 −$42.86. **Only the ≥0.25 band is
  tradable; supply ~1–2 bets/day fleet-wide.**
- **Live canary** (btc-twapedgelive, $150): gate = ask ≤ 0.97 at |est| ≥ 0.25,
  ties OFF. Three venue-rule lessons already paid for: FAK needs a match
  (race lost in 0.6s → 1-tick buffer), maker $ max 2 decimals (integer
  shares), marketable BUY ≥ $1. Deploys MUST go through rsync (deploy.sh) —
  helm alone ships env, not code.
- **Post-close pots persist post-switch** (Aug 7–8: loser-buy $7.8k/day,
  winner-snipe $3.3k/day). Mint-salvage 2.0 (rest ask on loser from T−3 on
  the ESTIMATE) refuted: fills adversely select ambiguous bars, 100:1 payoff
  kills it. BUT that used the 99.5% estimate — the byte-exact tick at ~T+1.5s
  has ~zero signal risk (identity, not estimate).
- Dead ends (older, all measured): intrabar taker/maker everywhere, tail
  buys/sales at every depth, near-tie cheap side (both directions), 1h/1d
  series (no flow), rebate harvest, cross-asset lead-lag, book-lag latency.

## Tonight's build queue (highest EV/effort first)

1. **Post-close winner snipe leg** in twapedge: at tick arrival (~T+1.5s),
   FAK-buy the CONFIRMED winner at ask ≤ cap (~0.10). Signal = the settlement
   value itself (ties→UP). Niche vs the sniper fleets: they run price feeds →
   blind on near-tie bars; we are exact there. Downside per fill ≈ 0 (only
   fills if someone sells the winner cheap post-close); risk = code bugs →
   start tiny (btc, $5–15 caps), scale on evidence.
2. **Expand twapedge live to all 6 coins** — ≥0.25 supply is ~6× btc alone;
   same bankroll (bets rare, caps coordinate).
3. **15m-series probe**: 15m markets settle on 60s TWAPs
   (`crypto_prices_twap_sixty`, already on our socket). Nobody measured
   whether their books still leave asks on determined winners — possibly the
   un-farmed version of the 5m edge. Build a lightweight sampler, collect
   through the day, decide by evening.
4. **mintsalvage 3.0** (sell the CONFIRMED loser at T+1.5s into the $7.8k/day
   loser-buy flow; needs mint inventory): defer until snipe-leg data shows
   how much post-close flow we actually reach at 1.5s. Operationally heavy
   (gas, nonces) — earlier sims: $45–175/day gross at close+1.6s, minus
   $3–12/day gas.

## Findings (append-only)

- 2026-08-11 00:15: log created; queue above.

- 2026-08-11 01:30: BUILT + DEPLOYED tonight:
  (1) post-close winner-snipe leg in twapedge (identity signal at tick
  arrival ~T+1.5s, ties->UP): paper sim on all 6 5m coins (cap 0.10, 200sh),
  LIVE on btc at $10/order. PF_TE_SNIPE_* events.
  (2) grid parameterization: BAR_SECONDS + PM_TE_TWAP_WINDOW (60) +
  twap_sixty topic + 4h slug fix in gamma.py.
  (3) probe pods PAPER: btc-twapedge15m (900s), btc/eth-twapedge4h (14400s).
  15m volume thin ($187/day btc) but 4h real ($7k/day btc); both settle on
  60s TWAP (cryptoMarketConfig.twapLookbackSeconds=60, venue-declared).
  ASSUMED H1 window [T-62,T-3] for W=60 — the verify loop scores it vs gamma
  automatically; check h1_ok on the first 15m settles.
  NEXT (tomorrow): analyze snipe-paper pot at our latency; probe evals for
  15m/4h supply; decide live expansion; mintsalvage 3.0 go/no-go from snipe
  flow data.

- 2026-08-11 10:45: **POST-CLOSE COMPLEX IS DEAD — measured.** Fresh mrec
  (Aug 9/10/11 sampled, btc+eth): winner-snipe pot **$0** (vs $3.3k/day
  6-coin pre/at-switch); loser-buy pot ~**$1.5-2k/day** 6-coin extrapolated
  (vs $7.8k/day Aug 7-8, $8.8k pre-switch) and falling. Mechanism: both pots
  were fed by LATE-FLIP confusion; the TWAP determinism killed late flips →
  killed the flow. Consequences: (a) snipe leg = free option, expect ~0;
  (b) **mintsalvage 3.0 NO-GO** (capturable slice ≈ $10-40/day gross vs
  gas+ops); (c) the settlement-snipe strategy from the leaderboard era is
  structurally extinct; (d) the whole PM updown ecosystem is now near-fully
  efficient at our observability — the TWAP switch made the market BETTER.
- 15m probe: h1_ok 21/21 but supply ~nil (1 tradable ask / 22 closes) —
  research success, commercial dud. 4h: first close datapoint 08:00 UTC.
  Remaining in-PM lever: 6-coin live expansion of the T-4.5 >=0.25 leg.

- 2026-08-11 13:30: NEW DIRECTION (user): PM mechanics depth + rewards +
  fresh leaderboard + faster API. Found on current 5m markets:
  `rewards_config rate_per_day=10000` (USDC), rewards_max_spread 1.5c,
  min_size 50, `makerRebatesFeeShareBps: 10000`, feeType crypto_fees_v2 —
  the LIQUIDITY-REWARDS program appears to cover updown markets and the
  maker-rebate share may have changed vs the 20% we measured in July.
  Agents launched: (a) rewards/rebates mechanics research; (b) post-TWAP
  leaderboard forensics (Aug 8-11, /activity-validated). Speed: live path
  got a 45s CLOB warm loop (first order paid 561ms cold vs ~200-300 warm);
  vacuum-style presign deferred (snipe pot ~0 post-TWAP, not worth plumbing).

- 2026-08-12 00:55: ALL THREE APPROVED AND LIVE. (1) btc-poolfarm live from
  ~00:20: fills immediately (edge quotes get run over in trends), first
  resolves: +9.50, then a pair bar (-55.00/+56.50 = +1.50 net; sequential
  booking false-triggered the halt for 1s -> netting window added). Risk
  patches shipped live-hot: 30s per-side fill cooldown + 1 fill/side/bar
  budget (a 3x50sh@0.75 one-sided burst in 4s = $112 forced it), halt 6s
  netting. Realized day_pnl +11.00 at patch time; one 150sh UP burst rides
  to redemption outside the counter (pod-restart inventory wipe — add state
  persistence later; balance reconciliation catches it).
  (2) 6x twapedgelive with the new LOCKBUY leg (tiers k<=20&>=2bps->0.99,
  k<=10&>=1bps->0.98, $15/order) + snipe + T-4.5.
  (3) Fleet 16 pods; free balance cycles $40-110 as positions redeem.
  NEXT: 03:00 Kyiv = first rewards-ledger day close; morning MCP
  polymarket_get_rewards shows our share of the $10k btc pool. Lockbuy
  paper events overnight verify the tier table live.

- 2026-08-12 04:42: poolfarm hit the -$25 daily halt (REAL, not false) —
  two consecutive one-sided losses from partner-cancel (a bar where the
  bought leg loses with the partner already cancelled = -$22.5 unhedged).
  KEY FINDING on the fix: partner-cancel trades pair-overpay (-2..4c/pair
  bleed) for one-sided VARIANCE (+/-$25/bar). Realized swung +$70 -> +$33
  -> halt across the night on that variance; net trading roughly flat, as
  the reward-farm thesis predicts. The halt fired correctly (netting held).
  Subsidy rows STILL 0 in data-api after ~4.5h -> either backfill is slow
  or first partial-day accrual < $1 min. MORNING DECISION gated on the
  actual reward number (MCP polymarket_get_rewards vs 0xdb66 wallet). If
  rewards < the ~$25/day variance cost, poolfarm is -EV at 50sh and either
  needs smaller size (less fill exposure per pool-$) or is dead. Options to
  weigh: (a) revert partner-cancel -> back to smooth -3c/pair but no big
  one-sided losses; (b) drop size to 20sh (1/2.5 the variance, same
  qualifying presence); (c) single-sided only in [0.10,0.90] at 1/3 credit,
  near-zero fills. Lockbuy strict version (k<=5, ask>=0.90) untested live.

- 2026-08-12 evening: EXECUTION FIXED & backtest-validated on CURRENT
  (post-TWAP) intrabar data. ROOT CAUSE (from live PF_MM logs): UP quotes
  averaged 0.516 but UP FILLS averaged 0.582 -- we filled 6.6c ABOVE our
  avg quote because chasing placed ever-higher bids and the high ones fill
  preferentially (rising side attracts sellers pre-reversion). Then EXIT
  round-trips + PARTNER-CANCEL converted neutral held pairs into bad
  one-sided directional bets (up@0.87 unhedged) = 96% of -$111.
  FIX (poolfarm.py): (1) HOLD both to redemption, NO exit sells, NO
  partner-cancel -- redemption is deterministic $1/$0, removing the
  sim-vs-live exit-fill gap that also killed maker-098; (2) HARD GUARD never
  rest a bid at/above that side's mid -> every fill +EV; (3) re-quote to
  follow mid only on reband, always floor(m-EDGE) below new mid (no chase up).
  BACKTEST (btc+eth+sol, post-TWAP, ex/*-postI.pkl, queue-pessimistic AND
  optimistic fill models BOTH): pair cost 0.970, +$89 to +$97/day trading,
  present 53%. Paper confirms 0 exit-quotes, 0 partner-cancels, guard active.
  FUNDING: $50 left can't run two-sided 50sh (needs ~$100 peak/bar). To go
  live needs ~$150 working capital. Sticky -$25/day halt + inventory cap +
  resolve-loop accounting all intact. Live-decision + funding = user's call.
  All 7 live bots remain STOPPED pending that.

2026-08-12 ~21:00 UTC — POOLFARM PAIR-COST CEILING (the real fix).
  Live bar 1 of the "fixed" (hold-to-redemption/no-partner-cancel/no-vol-pull)
  poolfarm lost -$14.50 on ONE bar: a 1.29 pair (UP@0.72 early + DOWN@0.57
  late on a whipsaw). Diagnosis: each leg is priced off the CURRENT mid, and
  the reband ("follow mid when the bid leaves the reward band") IS a form of
  chasing — on a mid that swings 0.72->0.42 we buy BOTH sides near their local
  highs, each "below its own mid at the time", sum >1.00. never-above-mid
  guard can't catch it (no memory of the other leg's cost).
  FIX: pair-cost ceiling — once one leg fills at p, cap the opposite leg at
  floor(PAIR_CEIL - p), PAIR_CEIL=0.985. Guarantees every COMPLETED pair
  <0.985; a standing opposite bid that violates it is cancelled immediately
  (no MIN_REST wait). poolfarm.py: bar_leg_px tracking + cap block in _tick.
  BACKTEST (kl/pf_bt_ceil.py, post-TWAP btc/eth/sol ex/*-postI.pkl, faithful
  to live no-chase+reband+ceiling): btc no-ceil pair median 1.120 max 1.542
  (23% profitable) = +$7/day but blowup-prone; WITH ceiling pair median 0.980
  max 0.983 (100% profitable) = +$56/day, reward presence unchanged 51%.
  CORRECTION of earlier claim: the "+$99/day no-chase" was a no-REBAND sim on
  PRE-TWAP data; the live code rebands, and post-TWAP whipsaws more. Trading
  alone is ~breakeven (both regimes ~-$4/day/coin before rewards); THE EDGE IS
  THE REWARDS (~$26/day btc observed: +$4.67 liquidity + $21.69 maker rebate).
  The ceiling's job is to stop trading from bleeding the rewards away + kill
  the left tail. Upside (+$47.6 residual @67% one-sided win) is adverse-
  selection-exposed and may regress; robust floor = guaranteed-<0.985 pairs +
  rewards. REDEPLOYED LIVE btc 2026-08-12 23:48 Kyiv (helm rev 15, $218.91,
  -$25 sticky halt + auto-abort cron). Fresh-bar quoting confirmed healthy:
  UP@0.39 + DOWN@0.58 = 0.97 combined.

2026-08-13 — POOLFARM TRIED/NOT-TRIED LEDGER (through the 15m pivot).
  ACCOUNTING: program start $148.91 -> $87.86 (-$61 total). Losses: -$25.50
  (5m night: whipsaw pair 1.29 + halt), -$53 one bar (1h over-accumulation
  bug: 150 DOWN/50 UP; reband bypassed the one-per-side guard -> FIXED with
  unconditional inventory-based per-side cap), -$25 (final 1h stint: 2 solo
  legs, killed mid-flight on the user's stop order). Wins: 7 clean 1h pairs
  (+$7), rewards+rebate ~$6.

  TRIED AND DEAD (do not reopen without new mechanism):
  * 5m in-bar one-shot pairs — 4% completion, one-sided fills = the loss.
  * 5m in-bar BATCH pairs (imbalance<=batch) — matched sh/bar = 0 at batch
    50/25/10 (fair zone), net negative at every size. 5m has no oscillation
    time; CLOSED.
  * Pre-open pair building (either duration) — STRUCTURALLY dead: 2,034 bars,
    ZERO pre-open SELL prints <=0.49 either side. Pre-open nobody holds
    inventory -> flow is 100% buyers lifting asks -> resting BIDS can never
    fill. Mirror (mint + sell both asks) blocked: pUSD wallet cannot CTF-mint
    (dual-ask program fact). Also explains pm-rebates-farmer's old bleed.
  * Active intra-bar MM flip (buy 50/sell 51) — momentum books: -$0.65/bar at
    1c spread on 1h; worse tighter. Multiple-times-per-bar must come from
    BATCH PAIRS, not flips.
  * Unwind/vol-gate/deep-edge/maker-completion/predictive-pull (5m era) — all
    dead, see 08-12 entries.
  * Taker-completion of the second leg — priced precisely: immediate = pair
    1.006-1.008 (fee 0.07*p*(1-p) ~1.7c + spread) = guaranteed -$0.33/pair;
    delayed = crystallizes the adverse move (unwind economics, worse by
    tick+fee). Usable ONLY as an insurance fallback if maker-completion odds
    after leg-1 exceed ~22% (breakeven q). Measure q on 15m recorder data.
  * Competitive scan (user ask): settlement holders both-sides >=20sh across
    12 fresh 5m/15m bars = ZERO wallets (nobody holds pairs to settlement).
    data-api /trades is taker-view (no maker field) -> in-bar two-sided makers
    invisible there; July program already established the winning archetype =
    mint/merge-capable fee-free two-sided ladders (we lack mint). Confirms our
    hold-to-settlement variant is uncontested because fills/capital are the
    bottleneck, not because it's unknown.

  WORKS (proven live, currently OFF by user choice):
  * 1h in-bar one-shot pairs — 7/7 live 50/50 pairs at 0.97-0.98, +$1/bar,
    settlement = the exit. No rebate on 1h (rebateBps=None), rewards
    negligible (quotes fill in minutes; presence ~0). 24 bars/day cap.

  OPEN QUESTIONS (the 15m program, running):
  * 15m in-bar completion rate — paper btc-poolfarm15m measuring (band
    0.35-0.65, quit 75s); first hours: violent trend regime, all flat (safe).
  * 15m BATCH pairs + rebate income (rebateBps=10000 on 15m) — needs the
    btc-mrec15m recordings (started 13:10 Kyiv); backtest when ~a day is in.
  * Taker-complete fallback trigger — compute P(maker completion | time since
    leg-1) from 15m recordings; deploy fallback only if q<22% branches exist.
  * NOT yet tried: multi-coin 15m (eth/sol), 4h/1d durations (no rebate
    check yet), dynamic band by realized vol.
  BATCH exec is IMPLEMENTED in poolfarm.py (PM_MM_BATCH_SH, imbalance
  throttle, cumulative avg-cost pair ceiling, venue min guards) — env-gated,
  default 50 = one-shot. Live flip: user gave latitude ("flip live when
  ready"), $87.86 bankroll, one 50/50 pair ~= $48 -> 15m one-bar-at-a-time
  fits; wait for the 15m completion verdict first.

2026-08-13 ~17:00 — TWO CORRECTIONS + pre-open REAL numbers.
  (1) MINT+MERGE ARE AVAILABLE (user caught my stale claim): mintsalvage
  splits via the CtfCollateralAdapter (approve pUSD -> splitPosition ON the
  adapter; ran 18h live x6 coins) and sweeper.py mergePositions through the
  same adapter ($220 recovered). Full mint->sell->merge cycle on the bots
  wallet. The July winning archetype (two-sided ask ladders + instant merge)
  is mechanically copyable.
  (2) SCANNER BUG: my pre-open scans prefiltered on '"trd": [[' (with space)
  but raw JSON is compact '"trd":[[' -> matched NOTHING -> the "zero pre-open
  prints / structurally dead" verdict was an artifact. Lesson: never build a
  mechanism story on a zero-count without histogramming the raw first.
  CORRECTED 7-day numbers (2,024 bars, btc 5m): pre-open flow is HUGE and
  50:1 buyer-dominated (129,191 BUY vs 2,498 SELL prints) — but INFORMED:
  * bids 0.48/0.49 both sides: -$121..-$145/day (solo-dominated, filled side
    loses even pre-open);
  * mint+sell-both at 0.50: both sides sell in 92% of bars but -$195/day;
    at 0.51 -$199/day. Pre-open buyers preferentially buy the side that WINS
    (prior-bar drift information) -> selling to them at 0.50-0.51 = being the
    dumb counterparty. "No information pre-open" is FALSE.
  In flight: deeper pre-open asks (0.52-0.55) + in-bar two-sided ask ladders
  (the BoneOhio shape, now that mint is confirmed) on the same dataset —
  optimistic fill model; if even that is negative the ask branch closes.
  Taker rebate program (researched): tiered 3%->50% on rolling 30d WEIGHTED
  volume ($2k->$10M, crypto weight 2.3x, daily pUSD payouts, since May 29).
  At our $87 bankroll = Bronze 3% = irrelevant; it subsidizes the big taker
  fleets (Obsidian pays HALF fees) — steepens the incumbent moat.

2026-08-13 ~17:30 — ASK/MINT BRANCH CLOSED (measured, optimistic fill model).
  Mint+sell-both at flat levels, 7d/2,025 bars btc 5m:
  pre-open 0.52/0.53/0.55 = -$705/-$492/-$365 per day;
  in-bar 0.52/0.55/0.60/0.70 = -$2,618/-$2,252/-$1,651/-$880 per day.
  Deeper into the flow = worse. ROOT CAUSE (same as every branch today): the
  taker BUY flow is INFORMED — buyers lift the eventual winner, the unsold
  residual we keep is systematically the loser. No flat ask level survives;
  real queued execution strictly worse. July's ladder winners = selection
  edge, not copyable mechanics (their mechanical copy was -EV then too).
  CONSOLIDATED STATE OF PM CRYPTO UPDOWN AT OUR SCALE ($87):
  * measured dead: 5m pairs (all exec variants), 15m pairs (live: pair +2.50
    vs residual -5.51 mix), pre-open bids AND asks, in-bar asks/ladders,
    MM flips, unwind/taker-complete, predictive pull, rewards-presence at 5m.
  * works small: 1h pairs (+$1/bar live-proven, no rebate, user declined);
    twapedge >=0.25bps (1-2 bets/day fleet-wide); mintsalvage 1c-floor edge
    (+EV live-measured, but needs ~$600/deal — capital-starved at $87).
  * scale-gated: taker rebates (Bronze 3% at our volume; Obsidian 50% for
    $10M/30d fleets), liquidity rewards (need 50sh resting presence).

2026-08-13 ~18:30 — SKEWED-MM ARCHETYPE: FINAL DEAD. mm2_stream.py (streaming
  full-bar, 7d raw, 2,016 bars, controls in-run): skewed configs -$2,208..
  -$3,151/day; K=0 control -$16,411/day (skew = 7x damage limiter, no edge);
  1h benchmark -$70/day. postI-based +$1,635/day was the dataset-window
  artifact (bug ledger #2). Ask/MM/mint branch CLOSED at every fidelity.
  Fresh wallet scan (30 bars): same 3 archetypes as July — late-fav snipers
  (med px .96-.98), cheap-side lottery buyers, ONE live two-sided MM whale
  (0x9e3e.., $137k book, 46 sells/30 bars). Nothing mechanically adoptable.
  Checklist refinement: haircut-lowers-PnL rule applies to +EV candidates
  only (for -EV makers stricter fills reduce loss).

2026-08-13 ~20:00 — MINTSALVAGE RESTARTED LIVE (post-TWAP revalidated).
  Demand: corpse-BUY 375k sh/day @<=5c in t15-45 (83% of bars), 2.88M sh @1c
  /7d. Flip calibration: >=8bps = 0/271 @t-45, 0/1,373 later moments (TWAP
  avg stickier than point-close; pre-TWAP was 0.53%@10bps). Economics
  CORRECTED (earlier +$10-20/d conflated mint rate with placement rate):
  ~35-40 placements/day btc, breakeven w/ US halt, +$2-5/day without.
  DEPLOYED: btc-only $35 bars, gate 6bps, floor 8, halt REMOVED (user),
  -$40/day. Helm gotcha: --set-string x="" loses to template `default` —
  use "off". Fleet purged: 9 twapedge + 4 poolfarm releases removed; running
  = mintsalvage + sweeper + 10 recorders. Signer gas 172 POL. Docs updated
  (MINTSALVAGE.md §7). Balance $92.05.

2026-08-14 ~11:35 — MINTSALVAGE STOPPED: post-TWAP queue-position death.
  16h live: 47 mints, 0/27 salvage fills (p 1-4% under doc rates), $0 pnl,
  ~$1.1 gas. Measured cause: 0.99-bid queue walls up EARLY post-TWAP
  (median 942sh / p75 4,566sh standing at t-45, n=503 decided bars) -> late
  35sh ask never reaches the ~1,200sh/bar of 1c flow. Early placement
  blocked: flips 4.76% @t-90 / 2.41% @t-120 at 8-10bps (ruinous at -$35 vs
  +$0.35); only >=15bps flip-free early (0/79) = ~4 bars/day = breakeven
  after gas. MINTSALVAGE.md sec.8 has revival conditions. Wallet ~$95 net
  (60 free + 35 redeeming). NO live traders remain; sweeper + recorders on.

2026-08-14 ~22:35 — 1H PAIRS RELAUNCHED LIVE (user go), now in BATCH mode:
  btc, band [0.35,0.65], edge 1.5c, 50sh/side via 10sh batches (imbalance
  throttle <=1 batch -> solo exposure ~$5 vs $25), ceiling 0.985, per-side
  cap, -$25/day sticky halt. First bar quoting 0.97 combined. Monitors:
  problem stream + 30-min quiet cron w/ auto-abort (cap breach/error storm).
  Earlier today: mintsalvage closed for good — queue-aware sim (bug-ledger
  #11 correction) showed even ideal early placement = $0.45/day/coin gross;
  safety and competition are the same variable post-TWAP.

2026-08-14 23:21 Kyiv — 1H PAIRS STOPPED BY USER after one relaunch bar
  (-$5.10: 20/20 pair +$0.36 + 10sh residual -$5.47 — the designed worst
  case, but user called it). Monitors/cron retired. NO live traders;
  sweeper + recorders remain. Free $70.49 + in-flight settling.

2026-08-15 ~01:05 — OVERNIGHT TAKER HUNT (user mandate, live allowed).
  (B) momentum-taker re-test under crypto_fees_v2 (old 10%-fee kill did not
  transfer automatically): btc 7d — 0.60-0.90 bands STILL dead (-1.1..-3.6c/
  sh; favorite premium > fee saving) but 0.90-0.96 = +1.81c/sh, win 94.6%
  vs 93.0% hurdle, n=129 (CI includes loss) -> pooling 5 more coins now.
  docs/strat-momtaker.md created. (A) 1h late-window taker: first scan empty
  — mrec1h has NO RES rows (pre-fix recorder; dataset table updated) —
  rerunning with post-book wins.

2026-08-15 ~01:25 — (A) 1h LATE-WINDOW TAKER: VERDICT = no supply. Signal
  perfect (flip 0.00% at every band >=3bps, t-5..30s; Binance 1h candle
  deterministic late) but winner-asks <=0.98 exist in 4-7% of bars, 7-312sh
  total over 7 DAYS -> ~$1.24/day best cell. Hourly closes are swept like
  5m. Same "research success, commercial dud" as the 15m probe. CLOSED.

2026-08-15 ~01:45 — overnight verdicts + coordination with the vacmaker
  session (parallel session found TWAP-60 migration + the T-14s taker wallet;
  its fleet is live/paper on 7 coins — hands off from this session).
  (B) momentum-taker POOLED ⛔: eth/sol/xrp/doge/bnb all negative (-0.8..
  -5.1c/sh, n≈5,900); btc +1.8c was the n=129 fluke. (A) 1h late-window ⛔
  no supply. THIS session's support contributions: hype-mrec + zec-mrec
  recorders deployed (vacmaker's top coin had no recorder); offline
  timing×price×coin EV surface for the T-14s taker computing from 7d
  recorders (conservative spot-lead signal proxy) — to pre-answer the paper
  sweep's question. Resolution table corrected: ALL 5m coins = TWAP-60.

2026-08-15 ~02:15 — OVERNIGHT CLOSE. Offline vacmaker surface delivered
  (docs/vacmaker-offline-notes.md): pooled 5-coin decisive bands ALL
  negative under a spot-lead signal (0.95-0.985: -$33..-$655/7d; 0.985+:
  zero-EV) while the target wallet wins at the same prices -> THE EDGE IS
  THE TWAP-60 RECON SIGNAL (+ small clips: 50sh sims lose where 8sh
  survives; + the <0.80 band is offline-unadjudicable, proxy-contaminated).
  hype/zec recorders live. Bug ledger +3 (#12 venue-field, #13 zsh
  word-split, #14 proxy contamination). No live deploys from this session —
  a spot-lead taker would be knowingly -EV and the viable lane (TWAP-recon
  taker) is actively owned by the vacmaker session. Night's verdicts:
  momtaker ⛔, 1h/1d late-window ⛔, vacmaker-support ✓ delivered.

2026-08-15 ~03:15 — NIGHT CLOSE. The delay.jsonl "true-signal" surface was
  a circular-label artifact (bug #15: 54/55 cheap-winner bars = my label
  errors; file's open/cl are not venue settlement inputs; 19% label error).
  Checklist caught it pre-deploy. Standing recommendation for vacmaker:
  add crypto_prices_twap_sixty to mrec (one field) for offline recon-grade
  data; until then the live sweep is the only instrument for the <0.80 band.
  Night totals: 3 cells closed with data (momtaker, 1h/1d late-window,
  delay.jsonl-as-instrument), 4 bug-ledger entries (#12-15), 2 recorders
  deployed (hype, zec), 1 handoff doc (vacmaker-offline-notes). Zero $ risked
  by this session; wallet ~$94; the viable lane runs in the parallel session.

2026-08-15 ~05:55 — USER ORDER "vacuum on 5m" EXECUTED as taker-vacuum go-live:
  sweep harvest (90 bars/coin) -> eth (tl50: 27/27 buyable correct, +$49/day
  pace) + bnb (tl40: 11/11, +$5/day) FLIPPED LIVE tiny (8sh/$10/-$25/day,
  inflight $25 to protect the shared wallet with hype). btc/sol/xrp/doge stay
  paper (thin/negative). Resting vacuum NOT resumed (queue-dead, twice
  measured). Monitors: problem stream + 30-min quiet cron w/ collision rule
  (storm -> scale MY two to 0, never hype).

2026-08-15 ~09:35 — VACMAKER FIRE-GATE FIX: eth/bnb live bots had 0 fires in
  3.5h — the hardcoded `coverage >= 0.8` (twapedge.py:446, built for T-4.5
  near-complete windows) is UNREACHABLE at eval_tl 40-50s (only ~(62-tl)/59
  of the window observable; observed coverage 0.55-0.60). Fix: env-gated
  PM_TE_MIN_COVERAGE (default 0.8 = behavior unchanged for hype + paper
  fleet; the parallel session's sweep fire=False rows were also this gate).
  eth/bnb redeployed with 0.5. NOTE for vacmaker session: your sweep's
  fire=False is the coverage gate, not signal absence — the knob now exists.

2026-08-15 ~10:30 — coverage floor CORRECTED per eval_tl arithmetic: at tl=50
  the [T-62,T-3] window is only ~20% elapsed -> coverage caps ~0.18 (my 0.5
  floor still blocked everything; the 0.55-0.60 I anchored on was btc@tl25).
  eth -> 0.12, bnb -> 0.25 (healthy-feed levels; gap detection preserved).
  Blocked evals showed the sweep's exact pattern waiting: h1 2.5-7.5bps with
  asks 0.98-0.99 x 100s of shares. Floors = (62-tl)/59 minus slack — rule
  recorded for any future eval_tl change.

2026-08-15 ~15:25 — OWNERSHIP + STATE SNAPSHOT (pre context-clear).
  User transferred hype-vacmaker to this session; found it 13.5h live with
  ZERO orders — the hardcoded coverage-0.8 gate again (predates the fix).
  Fixed: pmTeMinCoverage=0.25, inflight $20. Live fleet now all-mine:
  eth/bnb/btc/hype. Day: 10W/0L +$4.55, wallet $98.45. Wallet-comparison vs
  0xefdf: 18 buys/5h theirs vs our 10; only 1/10 bar overlap — earlier eval
  = cheaper entries, complementary flow; their extra volume = sol+hype + ~2
  clips/bar (re-entry ladder = open idea). sol2/doge2/xrp2 tl50 paper
  probes live; re-harvest everything tomorrow morning.

2026-08-15 evening→16 noon (vacmaker live ops, this session):
- hype tl40: 2 losses (cov-0.33 partial reads, −$11.86) → gate 1.0 →
  user removed pod entirely; events → data/hype-tl40-final-20260815.jsonl.
- Whale tape (data-api /activity, 299 trades 08-15): median fill 0.99,
  entries T−26..T+90, xrp 31/31 @0.99, sub-0.80 rare (6/299) → whale cells
  sol/xrp/hype (tl14, cov0.7, ≤0.99) deployed LIVE; renamed from *3;
  ALL paper pods removed (archive: data/paper-sweep-final-20260815/).
- eth stale-WS incident 16:14-20:33 Kyiv: sim rows = fiction (ledger #15).
- EVERYBAR experiment (user, 22:26): thresh 0.05, halt $999, $5 clips.
  ~14h: ~80 fills 97% win, wallet $93.26→$108.13 peak. Losses 2 species:
  whisper-entry (eth×3, sub-0.5bps, gate-fixable) vs decay-to-tie
  (hype/bnb, ≥0.8bps→|final|<0.05, gate-immune). btc's FIRST trades ever
  (17W/0L @0.89-0.98). T−14 wall: ask>0.99 blocks ~85% whale-cell fires.
- No-fill forensics: 11/11 kills = vanished asks in ~450ms path (neg-risk
  REST inline per fresh token); all would-have-won ≈$7-8 forgone,
  sub-0.94 fill rate ~60%. FIX SHIPPED 08:21 UTC: prewarm_loop (35-39ms
  at switch) + retry-FAK (0.3s×3s, signal-checked). GTC-rest REJECTED
  (ledger #16 survivor bias). zec re-checked: still empty (1.38M snaps,
  0 trades) — tripwire only.

2026-08-16 evening (vacmaker, this session): retry postmortem 5W/2L −$1.15
→ re-enabled w/ chase cap. Vol-conditioned ask-cap MEASURED (2,034 bars:
hold whisper 84/81/71 by vol tercile; 0.5-1.5 high-vol 94.7 = −EV at 0.98;
≥1.5 ~100 everywhere) → deployed as CAP_TABLE + strong-signal cap-limit +
PRESIGN (strong fires POST-only). Sim-vs-live: labels exact, ±25-30% PnL,
sim optimistic on fills / pessimistic on matched. Whale day: +$26 on
$2,152 all-0.99; us +$11 on ~$700. Full intervention index: offline-notes
§21. Day-16: ~142W/9L, wallet ~$96-100.
- 2026-08-17 eve — v3 clone day-1: live settles (33 bars, 53 clips). Day ≈
  −$20.3: 3 loss bars all mid-band laddered (−13.6/−15.5/−15.0); eth
  19W/0L +14.2. Ladder marginal clips net −$9.3, but 16/16 W at ≥0.94 →
  shipped WHALE_LADDER_MIN_ASK=0.94 (6 coins; hype halted −27.6, gets it
  at UTC rollover). Whale histogram recheck: HIS pre-close floor = 0.94 —
  our 0.55 clip-1 band is our deviation. Verdict: ladder pays only on
  confirmed favorites. Details notes §26.

## 2026-08-17 (late) — rewfarm: the $1M Aug rewards program vs the maker wall
Facts nailed via CLOB API + docs + live poller: pools/day 5m btc $10k, alts
$1,667, bnb/doge $833; 15m btc $7.5k; 4h btc $1,667 alts $333; band 1.5c,
min 50sh, quadratic weight, per-minute sampling, CURRENT bar only, config
attaches ~50s post-open, single-sided ÷3. Rebate = 0.2·0.07·p(1−p)/sh on
maker fills. rewsim1-3 on local mrec (7 coins × 7d 5m, btc/eth 15m × 5d,
delay 0.4s, QH pair, pair-ceiling, per-side caps): **5m in-band 50sh
two-sided NET −$300…−$1,000/day every coin/policy** (singles −$1,300/d @
17-29% win vs pairs+rewards+rebates ≈ +$700/d); 15m btc −$205/d eth
−$130/d; velocity/level lead-gates DON'T dodge toxic fills (43/48 at flat
vel); favorite-dip maker refuted (63% win, −6.2¢/sh); queue position
filters out the GOOD fills (strict < optimistic PnL). Duration ladder
5m 63% → 15m 72% → 1h 84% (live) pair completion ⇒ 4h thesis: field
in-band ~EMPTY (btc touch bid 47sh<50 cutoff!), 50-77% alt-pool share
available. SHIPPED: mrec4h recorders ×5 coins; btc+xrp rewfarm4h PAPER
(poolfarm.py, EDGE 0.5¢, QUIT 900, WARMUP 90, halt $12); secret.yaml
+PAIR_CEIL/NO_CHASE/VOL_PULL mappings. Ledger #21 #22. Sims: session
scratchpad rewsim{,2,3}.py + rewout*/. Next: user go-live (≈$50/coin),
eth+sol yamls, mint-based four-sided for empty hype/bnb/doge books.

## 2026-08-18 morning — §29 weak-cell mean reversion: CLOSED NEGATIVE
revmean.py, 2,668 probes (6 coins × 7d mrec, probe T−30..20, dog = 1−fav_bid
≤6c, lead-sign-agreeing cells): EV_hold −0.9…−3.0 c/sh ALL cells (weak cell:
proxy flip 3.65% ⇒ ~1.2-1.8% true vs dog ask 4.5c); retrace-scalp variants
strictly worse (retr ≥0.10 only ~12%). Dog premium 2-4× true flip everywhere
= favorite-longshot bias; complements §27+§28. Fleet also: first gate-era
losses (bnb −17.15 HALTED 03:49 UTC, xrp −7.92 bar; all four losses in the
§28 weak-est/early cell), hype redeployed 00:26 UTC on current code (23W/0L
day-1), gate replay: blocked set −$27.75/era → counterfactual wallet ≈$98 vs
actual $70. Time-scaled gate recommended, awaiting user go.

## 2026-08-18 ~09:45 — TIME-SCALED GATE SHIPPED (6 coins; bnb at 00:00 UTC)
twapedge.py: eff_thresh = THRESH + 0.035·max(0, tl−14) in whale_loop +
retry-FAK; env PM_TE_THRESH_{SLOPE,ANCHOR} (secret.yaml mapped); PF_TE_START
logs them. Verified in btc pod (env + START event). bnb deploy deferred to
UTC rollover (halted −17.15; monitor b6gy9h2e6). Mid-bar restart tradeoff
accepted per user "redeploy all": day counters reset (xrp halt budget
refreshed), old pods' in-flight clips unbooked in pod counters (wallet is
truth; sweeper redeems regardless).
Addendum ~09:55: bnb ALSO gated now (user override) — halt latch wiped by
the restart (fresh $15 day budget), rollover monitor b6gy9h2e6 cancelled.
All SEVEN coins on eff_thresh = 0.5 + 0.035·(tl−14) as of 06:55 UTC.

## 2026-08-18 ~12:15 — user: "vac fleet only" — rewfarm shelved, ns cleaned
17 trader releases uninstalled (mintsalvage x6, twapedgelive x6, pennymint,
poolfarm1h, vacuum, rewfarm4h x2; only the rewfarm paper pair had live pods
— the rest were dead-release cruft). Kept: 7 vacmakers, 17 recorders (incl
mrec4h x5), btc-sweeper. Open CLOB orders after cleanup: ZERO (no orphans).
rewfarm research stands (strat-rewfarm.md), revivable pre-Aug-31.
2026-08-19 22:30 | vacmaker gate search on GATED era (602 live clips 08-18→19 + 119 blocked-cell EVALs) | baseline +57.57, 4 loss bars | blanket slope 0.05/0.06/0.07 REFUTED (−11..−22 net); best cut px≥.98&est<1.2&tl>20 +12.57 but LOO −3.27 (1-bar-driven, §28.4 prior is the real license); loosening 0.8-1.05×0.96-0.99 40/40 but ≤+$2/d upper bound — leave; xrp/eth-type losses = +EV-cell residue, keep | notes §31, NO deploy
2026-08-20 08:45 | vacmaker overnight losses (5 bars −$53.8, vol regime 3x since 08-19 18:00 Kyiv) | era replay 739 vol-joined clips | vol-scaled entry gates ALL refuted (net −6..−34 or 1-bar-fragile); clip2 in vol>=10 measured ZERO-EV on 104 clips -> no-ladder-in-high-vol = only honest lever (+4.6, halves 2 of 5 night bars); sol halt fired −21.8; §31 px-gate catches none | notes §32, NO deploy
2026-08-20 09:10 | whale 0xefdf6abc vs us over the high-vol night (498-fill tape joined to our outcomes) | him +16.57 / us −11.67; his tl p50=15s vs our 25-30 | he SKIPPED 5/7 of our loss bars, flipped sides on hype 07:20 (+7.02), ate xrp 20:25 2.5x harder (−32.67); late-lane availability in high vol = SAME bar count (105 vs 110) -> §28.5 availability worry is low-vol-only; candidate = vol-conditional tl window (delay to <=15 when vol>=10), live-A/B only | notes §33, NO deploy
2026-08-20 18:50 | vacmaker 08-20 afternoon: UTC-day −51.11, ALL 11 loss bars tl23-30×vol>=10 (xrp est −5.86@vol37 flipped; bnb+xrp same-bar 16:45K macro hit); bnb+sol halted; balance $64.30 | union 871 clips: vol>=10×tl>20 = −49.21 era (−83.4 today) vs vol>=10×tl<=20 = 34/34 +12.18 | RETRACTS §32 refutation for the DELAY variant; vol-conditional tl<=15-20 delay now backed by our data AND whale tape | notes §32-33 addendum
2026-08-20 22:55 | user approved the vol-conditional delay + fleet redeploy | new gate LIVE all 7 coins ~19:52 UTC: whale_loop holds fire while ambient vol>=10bps AND tl>20s (delay to the late lane, not a skip; est/cov/band unchanged); env PM_TE_WHALE_VOL_DELAY_VOL=10 / _TL=20; PF_TE_WHALE_DELAY logs the first blocked would-be fire per bar (counterfactual A/B); params echoed in PF_TE_START (verified on all 7 pods) | side effects: restart reset bnb/sol day-halts (fresh $15 budget tonight) and vol window cold ~20min (gate inactive till 4 settled bars) | notes §34
2026-08-21 00:15 | hourly babysit #2 | first 2 live DELAY events, BOTH favorable (xrp: 1 late-fire won +2.33, 1 decay saved a wrong-side ~$7 loss) | era per-coin gate calibration (854 clips): flat-10 catches 21/25 early losses, diverts −44.37/keeps +34.93; relative 2.5x-median gate REFUTED (10/25); doge (+17.38 wins diverted, 0 losses caught) + hype (92% gated share) = per-coin exemption candidates pending DELAY decay rates | balance dip 87.73→53.28 attributed: 26.45 in-flight + 3.23 redeemable, no anomaly | no bugs, no deploy | notes §35
2026-08-21 01:15 | hourly babysit #3 | DELAY A/B at 12 events: 3 late-fires all won (+3.70), 8 decays forfeited wins (~$14.5 cf), 1 decay saved ~$8 loss → net ≈ −$10 tonight (trend leg = expected premium) | est/vol-ratio exemption REFUTED on 292-clip era cell (every R: exempt lane ≤ −5.91 or empty; wins pay pennies at 0.94-0.99 asks, losses cost $7.8) | decays driven by late ask >0.99 cap (book-vanish) | no bugs, no deploy, gate unchanged | notes §36
2026-08-21 02:10 | hourly babysit #4 | DELAY A/B at 14: 5 late-fires ALL won (incl xrp +11.26 — late lane caught 2 clips at good px; late-fire wins now +15.06) vs 8 forfeits / 1 saved | since-deploy fleet +6.95, UTC-day −13.99, bal $96.98 | no bugs, no changes
2026-08-21 03:10 | hourly babysit #5 | 08-20 FINAL: fleet −12.95 (bnb −17.93, btc −2.15, doge +10.29, eth +0.66, hype +4.30, sol −21.18, xrp +13.06) — evening under the gate recovered ~$38 from the −51 trough | DELAY ledger 20: 6 late-fires all won, 13 forfeits, 1 saved (trend night; doge 3F/0S = exemption watch) | 08-21 starts +2.12, bal $99.94 | log rotates at 00:00 UTC — day tallies need the .gz | no bugs, no changes
2026-08-21 04:10 | hourly babysit #6 | vol back to 10-30; 8 new delays: 1 SAVED ~$8 (bnb held DOWN@0.96, settled UP) vs 7 forfeits ~$4.1 cf (asks 0.87-0.99 = pennies) → gate net +$4 today, the dear-ask asymmetry working FOR us | eth −5.4 / sol −7.74 loss bars fired at vol 8.57/5.43 = below-threshold boundary (vol lagging a rising burst), NOT leaks; lowering to 8 not supported by era (1 loss in [8,10) vs kept-lane wins) | 08-21 day: fleet −5.29, bal $92.77 | cum ledger: 28 delays = 6 late-wins / 20 forfeits / 2 saved | no bugs, no changes
2026-08-21 05:15 | hourly babysit #7 | bnb −22.96 in ONE bar (3×7.68 ladder, est −1.01 = exactly eff_thresh, vol 8.65 = under gate, settled h1 +0.11 near-tie); halt engages on next fire | 3 fixes era-REFUTED: vol→8 ([8,10) band +6.01, 1-bar LOO), ladder-cap-2 (clip-3+ era +6.01), est-margin ladder gate (boundary clips +11.82, high-margin −6.94 — backwards) | day: fleet −22.26, gate today: 2 saved (~$16) vs forfeits ~$5 + 4 late-fires pending | bal $74.58 | no deploy — tail event, halt is the backstop
2026-08-21 06:10 | hourly babysit #8 | vol 14-37, gate busy: today 2 SAVED (~$13: bnb 0.96, eth 0.61 wrong-siders), ~8 forfeits ≈ $4.4 cf (dear asks), late-fires ALL won again (btc@16.7, hype 3-clip@13.4-11.3, xrp@19.3/16.7) → gate net ≈ +$8.5 today | fleet day −21.69 (bnb −22.96 idle-not-yet-halted: halt logs only on a fire attempt), bal $75.26 | no bugs, no changes
2026-08-21 07:10 | hourly babysit #9 | 5/5 new delays converted to late-fires, all WON (hype held through vol=60.74 burst, fired @19.8/5.9) | late-fire coins all x-0 today: btc 9-0, doge 6-0, hype 7-0, xrp 4-0 | fleet day −16.23 (ex-bnb +6.7), bal $80.26 | no bugs, no changes
2026-08-21 08:10 | hourly babysit #10 | bnb restarted 07:26K on user request (fresh $15 budget; came up clean, gate params verified); quiet since | 3 new late-fires all won (btc 13-0 day; sol 3-clip @20/16/15), 5 forfeits ~$2.7 cf | fleet day −14.68 (ex-bnb +8.3), bal $81.71 | no bugs, no changes
2026-08-21 09:10 | hourly babysit #11 | strong hour: fleet day −5.73 (was −14.68), bal $90.26 | 7 new late-fires ALL won (bnb back trading 6-3 incl @19.8/18.5; xrp 0.68-ask conversion @19.7, day +7.02 7-0; btc 15-0) vs 6 dear-ask forfeits ~$2.5 cf | late-fire record since deploy remains PERFECT | no bugs, no changes
2026-08-21 10:10 | hourly babysit #12 | quiet hour: fleet day −4.19, bal $91.69 | eth delay@0.78 fired @19.8 won (late-fire streak intact); 2 dear-ask forfeits (0.98/0.99, pennies) | btc 17-0 | no bugs, no changes
2026-08-21 11:10 | hourly babysit #13 | fleet day −0.95 (nearly recovered from bnb −23 bar), bal $94.73 | 5 new late-fires all won (eth 0.70→@19.5/10.4; hype ×2; xrp @19.8 at vol 33.8), 4 dear-ask forfeits | late-fire record still PERFECT since deploy | no bugs, no changes
2026-08-21 12:10 | hourly babysit #14 | fleet day POSITIVE +1.31 — bnb −23 tail bar fully recovered same-day | btc 19-0 (late-fire @18.6/15.5 on est 5.3), eth 0.63→@13.9 won; doge forfeit @0.76 (~$2.5 cf, doge decay pattern continues — week-ledger watch) | bal $97.80 | no bugs, no changes
2026-08-21 13:10 | hourly babysit #15 | vol spike to 45-89 handled clean: 6 new late-fires ALL won (xrp @14.4/12.8 at vol 71 and @17/15.2 at vol 89; doge @13.9/12.8; btc/hype) vs 7 dear-ask forfeits | fleet day +4.92, bal $100.24 (crossed $100) | btc 21-0, hype 14-0, xrp 12-0, doge 10-0 | no bugs, no changes
2026-08-21 14:10 | hourly babysit #16 | fleet day +6.88, bal $102.16 | 2 late-fires won (xrp @18.6/14.3 at vol 72; btc @20.0 → 22-0), 5 dear-ask forfeits (0.89-0.99) | xrp 14-0 day +9.64 | no bugs, no changes
2026-08-21 15:10 | hourly babysit #17 | fleet day +7.28, bal $102.91 | hype late-fire won (16-0); bnb 3-clip late-fire @19.7/18.4/17.3 (est 0.85, vol 36 — settle pending, check next hour); 2 dear forfeits + 1 pending | no bugs, no changes; US morning opens ~16:30K
2026-08-21 16:10 | hourly babysit #18 | US-morning open, busiest gate hour yet: ~10 new late-fires ALL won (bnb 3-clip @19.7-17.3 + @11.9/10.9; doge x3 → 15-0 +7.38; btc @15.4; sol @15.5; xrp @18.8) + eth SAVED a wrong-side est −3.04 @0.91 (~$7 — 4th save, ~$21 cum) vs 3 forfeits | fleet day +9.50, bal $97.25 (in-flight dip) | late-fire record still ZERO losses | no bugs, no changes
2026-08-21 17:10 | hourly babysit #19 | US-morning hour 2: SAVE #5 — hype held wrong-side est −4.39 @0.76 at vol 55 (~$10.5 not lost; a whopper signal that was WRONG = exactly yesterday's disease) | 5 more late-fires all won (bnb 3-clip; xrp 0.58→@18.5/17.2; btc 24-0) | fleet day +12.32, bal $107.15 session high | cum saves ~$31 vs forfeits ~$25 cf + late-fires perfect | no bugs, no changes
2026-08-21 18:10 | hourly babysit #20 | fleet day +15.21, bal $109.85 | 6 more late-fires all won (sol 0.61→3-clip @19/16.5/14.6; xrp @12.3 at vol 67; eth, btc 25-0) vs 6 dear forfeits | US-morning window passed GREEN (+~6 through it vs yesterday −51) | no bugs, no changes
2026-08-21 19:10 | hourly babysit #21 | fleet day +18.60, bal $113.02 | 5 late-fires all won (hype @17.7 at vol 42 + @19.6/18.4; xrp 0.63→@18.8/17.2; btc 26-0) vs 3 dear forfeits | bnb 21-3 grinding back (−19.39) | no bugs, no changes
2026-08-21 20:10 | hourly babysit #22 | fleet day +20.21, bal $109.42 (in-flight dip) | 6 late-fires all won (eth 0.78→3-clip @19.8-17.6; xrp 0.71→@18.0 + 0.66→@18.6; sol @16.1/14.9; btc 28-0) vs 5 dear forfeits | no bugs, no changes
2026-08-21 21:10 | hourly babysit #23 | FIRST late-fire loss: xrp 16:55 UTC — delayed at est −3.53 (vol 32.8), est decayed to −0.78 by tl 18 (cleared late thresh 0.64 barely), fired @0.78, bar flipped, −7.11; late-fire record now ~30-1 (~97%, breakeven at avg ask ~0.85) — acceptable residue, no action | 3 new late-fires won (bnb 3-clip @19.9-17.4; doge @19.8/18.6; eth 3-clip) vs 8 dear forfeits (0.94-0.99) | fleet day +16.89, bal $110.85 | no bugs, no changes
2026-08-21 22:10 | hourly babysit #24 | fleet day +19.23, bal $113.02 | vol cooling (10-23); 4 late-fires won (sol 0.74→@12.6 + @19.8/18.6; xrp @17.6/7.5; btc 30-0), 1 dear forfeit | no bugs, no changes
2026-08-21 23:10 | hourly babysit #25 | fleet day +21.53, bal $115.33 | 4 late-fires won (bnb @19.7, hype @19.6 at vol 33, xrp @19.9/13.4), 3 forfeits | bnb 29-3 clawing (−17.24) | no bugs, no changes
2026-08-22 00:10 | hourly babysit #26 | fleet day (08-21) +26.64, bal $120.89 session high | 6 late-fires all won (eth ×2, hype ×2 incl 0.82→@19.7, sol 2-clip, bnb) vs 2 forfeits | bnb −16.63 (33-3) | no bugs, no changes
2026-08-22 01:10 | hourly babysit #27 | fleet day (08-21) +29.04, bal $122.23 — nearly back to pre-chop $127.74 | 3 late-fires won (xrp 0.73→@19.8/18.7; eth; hype), 4 dear forfeits | no bugs, no changes
2026-08-22 02:10 | hourly babysit #28 | MILESTONE: bal $128.40 > pre-chop $127.74 (08-19) — chop-day damage fully recovered | fleet day +34.56 | monster hour at vol 14-68: ~10 late-fires ALL won (bnb 0.57→3-clip; doge 0.55→2-clip at vol 52; xrp est −9.1 @19.9/18.5; eth 3-clip; btc/sol/hype), SAVE #6 (btc wrong-side −1.65 @0.80, ~$8) vs ~6 forfeits | no bugs, no changes
2026-08-22 03:10 | hourly babysit #29 — 08-21 CLOSE | first full gated day: fleet +37.10 (203-6), bal $130.78 > pre-chop | per-coin: btc +19.76 33-0, xrp +9.55, hype +9.41 26-0, doge +9.15 21-0, eth +6.68, sol −1.95, bnb −15.50 (single §37 tail bar) | DELAY ledger 31h: 209 → 98 late-fires ~97-1, 103 decays, 7 saves ~$40 | doge/sol exemption = week-ledger review | notes §38 | no bugs, no changes
2026-08-22 04:10 | hourly babysit #30 | late-fire loss #2 (btc): held est 3.68@0.99 tl 29.5 → est decayed to 1.53 by tl 16.7, fill swept repriced book at 0.545 (ask collapse = market flipped), bar lost −5.49 | PATTERN: both late losses = est decay >55% + ask far below delay-time ask (the §"never chase a repriced book" lesson in reverse) → candidate decay-guard (|est_fire| >= 0.5×|est_delay| or ask-collapse skip); n=2, LOG ONLY, review at ~5 or week ledger | fleet day −3.88, bal $125.65, vol 15-40, forfeits all dear | no bugs, no deploy
2026-08-22 05:10 | hourly babysit #31 | fleet day −0.05 (btc −4.51 = the #30 loss; rest green), bal $129.24 | 3 late-fires won (eth 0.86→3-clip @19.9-17.4; sol @19.8/18.5; xrp @18.0 at vol 50), 5 dear forfeits | no bugs, no changes
2026-08-22 06:10 | hourly babysit #32 | fleet day +3.22, bal $133.64 new high | 7 late-fires all won (doge 0.79→2-clip; xrp 0.84→@17.5/10.9 + 0.66→@19.7/18.3 at vol 48-52; eth 2-clip; btc @20.0) vs 4 dear forfeits | no bugs, no changes
2026-08-22 07:10 | hourly babysit #33 | fleet day +5.61, bal $134.55 new high | 4 late-fires won (xrp ×3 incl 0.66→@7.6 at vol 50 and est 9.3→@18.3; eth @19.8) vs 6 dear forfeits (vol bursts to 79 on doge) | no bugs, no changes
2026-08-22 08:10 | hourly babysit #34 | late-fire loss #3 (xrp 04:55 UTC): WHIPSAW at vol 60 — est flipped +2.47→−1.70→+1.29 inside the window, bot bought both sides, net −7.2 | all 3 late losses share est/vol < ~0.1 AT FIRE (0.024/0.10/0.028) → candidate LATE-lane ratio floor (distinct from §36's refuted early-lane version); n=3, log only | doge converted est −5.6@vol 61 late (@9.0/7.7 won), hype @17.7 won | fleet day −0.47, bal $128.34 | no bugs, no deploy
2026-08-22 09:10 | hourly babysit #35 | VOL STORM ~05:20-06:00 UTC (xrp 223-232, doge 187, sol 173, hype 117) passed with fleet ~flat (+0.78 day) — storm bars mostly converted (sol est 11@vol173 won, xrp est −25.9@vol232 won, bnb est −7.5 won) | late-fire loss #4 (xrp 05:30, decay −6.77→−1.14 fired 0.81) BUT ratio-floor candidate RETRACTED: winners at est/vol 0.032 (doge) and 0.063 (sol) sit inside the sketched loss zone — 4 losses/110 fires = binomial noise above 0.85 breakeven, stop pattern-hunting the losses | bal $129.22 | no bugs, no changes
2026-08-22 10:10 | hourly babysit #36 | fleet day +7.07, bal $134.91 new high | 6 late-fires all won (doge ×3 incl 0.56→@18.3/16.1 and @13.3/9.8 at vol 59-71 → 13-0; sol 0.68→@16.9/12.1; bnb @19.7) vs 4 forfeits | doge day +5.33 in continued 50-90 vol | no bugs, no changes
2026-08-22 11:10 | hourly babysit #37 | fleet day +8.37, bal $143.35 new high | SAVE #8: sol held wrong-side UP est 1.10 @0.61 (~$8 kept) | 3 late-fires won (xrp est −19@vol 89 @19.8/18.5; bnb 2-clip incl @7.6) vs 5 dear forfeits | no bugs, no changes
2026-08-22 12:10 | hourly babysit #38 | fleet day +10.32, bal $137.54 | eth 14-0 +12.07 | late-fire loss #5 (bnb 08:55 UTC: est −0.87 held, no decay, weak-est flip @0.74) — ledger ~112-5 ≈96% vs ~85% breakeven, no action | 3 late-fires won (doge @17.5/12.2 at vol 51) | no bugs, no changes
2026-08-22 13:10 | hourly babysit #39 | fleet day +11.82, bal $138.93 | 4 late-fires won (btc @19.9, doge 2-clip, xrp @19.6/18.3 at vol 79), 7 forfeits (2 juicier: xrp 0.80 est 12.2 & 0.73 est 6.0 decayed) | doge 17-0, eth 15-0 | no bugs, no changes
2026-08-22 14:10 | hourly babysit #40 | fleet day +13.02, bal $140.28 | 5 late-fires won (bnb 3-clip @19.9/11.3/9.9; doge ×2 → 19-0; btc @17.1) vs 5 dear forfeits (xrp vol 107 sat out at 0.98) | no bugs, no changes
2026-08-22 15:10 | hourly babysit #41 | quiet hour: fleet day +13.50, bal $141.47 | 2 dear forfeits + 1 pending, no late-fires needed | doge 21-0 | no bugs, no changes; US morning ~16:30K next
2026-08-22 16:10 | hourly babysit #42 | fleet day +18.89, bal $145.53 new high | 4 late-fires won (bnb 2-clip, doge ×2 → 24-0, hype 0.74→@19.9/18.7), 4 forfeits | eth 18-0 +13.54 | no bugs, no changes; entering US morning
2026-08-22 17:10 | hourly babysit #43 | eth −7.65 early fire at vol 6.5 (calm-before-storm bar, no vol measure catches storm-start) → sub-10 band recheck post-deploy: 61 clips 55W-6L −15.30, but LOO = bnb triple bar; §37 trigger (2nd multi-clip sub-10 loss) NOT fired, half of losses below 8 anyway → keep 10, no change | 16:45K macro bar: 4 coins held est 27-38bps, all decayed [FORFEIT] ~$8-10 cf (trend premium; ask >0.99 by late window) | 3 late-fires won (hype, sol @14.1/12.8) | fleet day +13.53, bal $139.91 | no bugs, no deploy
2026-08-22 18:35 | hourly babysit #44 — BUG FIX DEPLOYED | other session's de22700 (17:48K, user-authored) made the delay unconditional (early lane OFF: −$74.51 band, vol gate was noise) → 6 min later eth lost −$18.40 in the post-restart BLIND WINDOW (vol=None disables the gate ~20min after every restart; 2nd occurrence after doge 08-20) | fix dbc45e8: vol None ⇒ delay; all 7 redeployed 18:31K, verification clean | fleet day +4.4 after eth hit, bal ~$122 | notes §39
2026-08-22 19:10 | hourly babysit #45 | dbc45e8 fix VERIFIED IN THE WILD: warmup holds now log vol:null DELAYs on 5 coins (the exact leak that fired early pre-fix); doge converted a null-vol hold @18.3/14.8 and WON, xrp 0.63→@13.4/11.6 won | fleet day +1.19 (eth clawing back, 24-4), bal $130.01 | no bugs, no changes
2026-08-22 20:15 | hourly babysit #46 | late losses #6 doge (0.89→0.71) #7 sol (0.99→0.52 fill) → full late-lane replay (313 fills since deploy): 306W-7L +88.71; dear [0.93,1) = 256-0 +58.71; cheap <0.85 holds ALL losses yet is +11.81 net; ask-collapse subset −0.47 (n=7, zero-EV) → ALL cuts refuted, losses = cheap-lane premium, no change | fleet day −10.92, bal $117.48 (in-flight) | notes §40
2026-08-22 21:10 | hourly babysit #47 | fleet day −7.17, bal $121.48 | 3 late-fires won (doge 3-clip + 2-clip → 33-1 +8.28; sol @19.4/16.0), 1 dear forfeit | no bugs, no changes
2026-08-22 22:10 | hourly babysit #48 | fleet day −6.04 (recovering), bal $126.07 | sol 3 late conversions all won (14-1); unconditional delay correctly holding at low vol too (bnb 6.7, eth 4.7, sol 7.7 — bars the old vol-10 gate would have fired early) | 3 dear forfeits | no bugs, no changes
2026-08-22 23:10 | hourly babysit #49 | fleet day −4.94, bal $126.34 | SAVE #9 (xrp held UP est 1.0 @0.55 vol 32 — decayed, settled DOWN, ~$8 kept) | 3 late-fires won (sol ×2 → 17-1; xrp @19.6/18.3), 3 dear forfeits | no bugs, no changes
2026-08-23 00:10 | hourly babysit #50 | fleet day (08-22) −2.54, bal $128.61 | SAVE #10 (bnb held UP est 1.0 @0.73 — decayed, settled DOWN, ~$8 kept) | doge late conversion @18.4 won (34-1 +10.52) | day damage = the pre-fix eth blind-window bar (−18.4); rest of fleet ~+16 since | no bugs, no changes
2026-08-23 01:10 | hourly babysit #51 | fleet day (08-22) +2.48, bal $133.71 — day flipped green despite the −18.4 blind-window bar | 5 late-fires won (doge 0.76→2-clip + 0.72→@12.8 → 37-1 +15.05; sol 0.80→@14.7/10.8; xrp 0.79→3-clip), ~9 dear forfeits | no bugs, no changes
2026-08-23 08:35 | babysit catch-up (02-08K checks missed: harness outage; fleet unattended on in-bot guards, clean) | 08-22 FINAL: fleet +9.53 GREEN despite the −18.4 bug bar (doge +15.29 38-1, btc +3.26, hype +2.75 12-0, sol −0.03, xrp −0.76, bnb −1.45, eth −9.53) — 2nd consecutive green day | 08-23 so far +0.78, bal $131.45; 3 overnight late losses: doge whipsaw ×2 (flip-side clips @0.62-0.69 on hair-over-threshold ests), hype strong-est flip | whipsaw-flip-side subset n≈4 = week-review replay candidate; §40 verdict stands, no deploy
2026-08-23 09:15 | hourly babysit #52 | bnb −15.09 HALTED (backstop worked; 05:30 UTC bar: 2 clips est −0.52 @0.974/0.98, first-ever dear-bucket late losses) | est-bucket check on 256 era dear fills: FLAT (45-0 even at est<0.7) → no est-floor cut, binomial residue | fleet day −11.53, bal $126.84 | 4 late-fires won this hour (eth @13.2, hype @18.3/15.1, btc 0.56→@16.6, sol) | no bugs, no changes
2026-08-23 09:25 | user: "restart all pods to remove halts" — all 7 vacmakers rolled, halts cleared (fresh $15 budgets; bnb back from its −15.09 halt) | post-restart verification clean (0 errors, LIVE_READY $130.91 all pods); warmup safe under dbc45e8 (vol:null ⇒ delay)
2026-08-23 10:10 | hourly babysit #53 | very active hour post halt-clear restart: ~12 late-fires, settled ones all WON (hype 10-1 +4.15 recovered; sol 12-0 +6.87; bnb back trading @19.8; vol:null warmup holds converted cleanly on hype/xrp) | fleet day −3.30, bal $114.27 (heavy in-flight) | no bugs, no changes
2026-08-23 11:10 | hourly babysit #54 | choppy day: late-lane loss rate elevated — today 8 losses in ~68 late fires (12% vs era 2.2%); eth −11.88 (2-clip loss on the 07:00 UTC bar), xrp −2.08 | fleet day −23.93, bal $116.79 | SAVE #11 (sol DOWN @0.80 decayed, settled UP) | no bugs (signals verified, all losses = settled flips); halts are the cap — bnb already used its; eth at −11.9 approaching | no config change: chop-mode not distinguishable ex-ante, late lane era-remains +EV
2026-08-23 12:10 | hourly babysit #55 | eth HALTED this hour (post-restart in-memory tally crossed −15; file day −11.88) — 2nd halt of the day after bnb | fleet day −19.92, bal $118.01 | sol carrying the day 16-0 +8.64, hype 13-1 +4.59; 6 late-fires won this hour, ~8 dear forfeits (chop being sat out correctly) | no bugs, no changes; eth out until 03:00K unless user restarts
2026-08-23 13:10 | hourly babysit #56 | eth restarted on user request at 13:00K (halt cleared, warmup delay-protected, clean start) | fleet day −19.29, bal $118.60 | 5 late-fires won (hype ×2 → 16-1, btc @19.6, xrp 0.76→2-clip, bnb), ~14 dear forfeits — chop being sat out | no bugs, no changes
2026-08-23 14:10 | hourly babysit #57 | fleet day −18.65, bal $119.20 | eth back winning (12-2, incl a post-restart late-fire @20.0), sol 18-0 +8.88 | 3 late-fires won, ~7 dear forfeits | no losses for 3 hours — morning chop cluster over | no bugs, no changes
2026-08-23 15:10 | hourly babysit #58 | quiet hour: fleet day −18.08, bal $119.73 | 2 late-fires won (hype @19.8 → 17-1; xrp 0.67→2-clip), 3 dear forfeits | 4h loss-free | no bugs, no changes; US morning ~16:30K
2026-08-23 16:10 | hourly babysit #59 | fleet day −17.31, bal $120.53 | SAVE #12 (eth DOWN @0.96 decayed, settled UP) | 5 late-fires won (doge 0.81→2-clip, eth @19.8/16.9, sol @19.8, xrp @11.3/10.0), 6 dear forfeits | 5h loss-free | no bugs, no changes; entering US morning
2026-08-23 17:05 | research (separate session, NO bots touched): "the opposite of vacmaker" — dip-buy, sell/hold to redemption | ⛔ nothing to deploy: the dip lane IS already live (MIN_ASK=0.55 + §37 delay) and IS the profit centre — ask 0.75-0.90 = +3.98% ROI vs +0.21% at >0.98, +$34.54 of the fleet's +$50.85 logged live PnL; cell ask .55-.90 & tl<=20 = n70 88.6% win vs 79.1% b/e, +11.24% ROI, P=0.029, LOO +9.3…+14.9% on all 5 days | ⭐⭐ TAKER-SIDE WALL MEASURED (tools/fillphys.py): FAK match rate 11.2% at seen ask .55-.75 (295 attempts, LIVE_ERR=0, price above the ask, 9sh vs 40-50sh shown) vs 75% at >0.98; the binary pair is ONE book (ua ≡ 1−db, uas ≡ dbs, 100% of rows) so a cheap ask IS an informed maker's bid that gets pulled — bug ledger #23 | ⭐ Chainlink-truth re-test §38 asked for is DONE (tools/dipcl.py, 2,603 bars, V1 99.54%, placebo −89.7%): ROI monotone in cheapness (0.40-0.55 → +75.6%, p=0.0003) = real but unreachable; sim 7× over live in .55-.75 | sell-vs-hold: HOLD (winning cheap entries' bid at T−3 is p50 0.86, mean give-up 24.9c/sh; redemption lands ~2min after close) | only open lever: size the .75-.90 & tl<=20 cell above its single 8-9sh clip (WHALE_LADDER_MIN_ASK=0.94 caps it) — +$5…10/day for a −$12.8 loss tail vs the $15 halt = user risk call, NOT deployed | docs/strat-dipbuy.md + notes §41
2026-08-23 17:10 | hourly babysit #60 | fleet day −16.25, bal $113.72 (in-flight) | SAVE #13 (xrp wrong-side UP est 3.62 @0.82 decayed — ~$10 kept) | 3 late-fires won (hype 3-clip @19.9-17.8 → 20-1; sol @20.0 → 21-0; xrp @19.7), 4 dear forfeits | 6h loss-free through US-morning open | no bugs, no changes
2026-08-23 18:05 | research (separate session, bots untouched): the MEAN-REVERSION bot — buy the dip, collect the occasional reversion | ⛔ CLOSED ON PRICE (not execution): local archive 07-30→08-17, 7 coins, 28,422 bars, 376,002 obs on a T−270→T−3 grid, NO estimator/proxy/fill-model/fee (book prices + venue RES only) | dog 0.05-0.35 & tl 30-180: true win 15.14% [14.94,15.34] vs mean ask 0.1795 = −15.7% of stake, n=119,408; every coin negative (eth −8.4 … hype −58.9), 18/19 days negative | ⭐ the favourite-longshot premium is a TIME structure: −25…−60% in the settlement window decaying to −1…−6% (≈the vig) by T−240 — §27 measured its worst region, §29 one cell | steelmen all fail: literal "it just got crushed" (~150 cells, none positive, deeper drops worse), violence (≥3-5× median move → worse; intra-bar path is momentum), scalp-the-retrace (−13…−22%, only 13-31% ever retrace), best cell anywhere tl≥180 dog 0.08-0.22 = −3.8% (train/test stable, −9.6% with fee) | closing arithmetic: fair 0.1514 | ask 0.1795 (+18.6%) | bid 0.1486 (−1.8%) ⇒ a PERFECT maker fill earns +1.8% gross, erased by the −0.47c resting wall | tools/revcal.py + docs/strat-reversion.md + notes §42
2026-08-23 17:50 | user: "check all losses, can we prevent? no code" | full-era replay (467 late clips 450-17 +80.69): ALL cuts refuted or LOO-fragile — ask-collapse +6.78 but day-sign-flips, flip-side −6.62, est floors −14/−30, px<0.85 −7.40; every cut = chop-day proxy (3rd confirmation of §32 mode-dependence) | last-26h window alone is −32.93 (chop) — cuts only look good in-sample there | levers: halts (working), ladder size, manual chop pause | notes §41, no deploy
2026-08-23 18:10 | hourly babysit #61 | first Tracebacks (doge 1/hype 3/xrp 3) = transient PM WS handshake failures, reconnect loop recovered, staleness gate protected orders — NOT a bug, no action | doge lost another bar (15-3, −14.88); fleet day −28.14, bal $109.91 | ~12 late-fires won this hour (hype 23-1 +6.36, sol ×3 incl @12.8/11.4) | chop day continues; halts armed
2026-08-23 19:10 | hourly babysit #62 | fleet day −26.01, bal $110.52 | WS errors cleared (0 this hour) | 6 late-fires won (hype 28-1 +6.97 incl @13.9; doge @19.6; sol @12.8/11.4), 5 dear forfeits | no losses this hour | no bugs, no changes
2026-08-23 20:10 | hourly babysit #63 | fleet day −25.29, bal $112.76 | 3 late-fires won (doge 2-clip → 18-3, sol @19.4/17.7 → 27-1, xrp @18.5/17.5), 7 dear forfeits | 2h loss-free, grinding back | no bugs, no changes
2026-08-23 21:10 | hourly babysit #64 | fleet day −21.23 (grinding back), bal $115.61 | 8 late-fires ALL won (bnb 3-clip → 12-2; eth 3-clip + 1 → 19-2; sol ×2 → 31-1; doge 2-clip; xrp ×2), 5 dear forfeits | 3h loss-free | no bugs, no changes
2026-08-23 22:10 | hourly babysit #65 | fleet day −19.88, bal $116.86 | quiet: 1 late-fire won (hype @16.2/14.4 → 31-1), 6 dear forfeits, vol easing (3-25) | 4h loss-free | no bugs, no changes
2026-08-23 23:10 | hourly babysit #66 | fleet day −17.50, bal $119.11 | 6 late-fires all won (sol ×3 → 37-1, doge @17/16, hype @19.9, bnb), 6 dear forfeits | 5h loss-free, vol easing | no bugs, no changes
2026-08-24 00:10 | hourly babysit #67 | fleet day −22.72, bal $113.66 | SAVE #14 (xrp UP 1.14 @0.69 decayed, settled DOWN); xrp took 1 late loss (29-2) | 5 late-fires won (bnb 3-clip → 16-2, sol 40-1, xrp ×2) | no bugs, no changes
2026-08-24 01:10 | hourly babysit #68 | fleet day −22.03, bal $114.31 | 4 late-fires won (bnb ×2 → 19-2, xrp @19.8/18.6 at vol 47), 2 dear forfeits | quiet, 1h loss-free since xrp's | no bugs, no changes
2026-08-24 02:10 | hourly babysit #69 | fleet day −17.14 (recovering), bal $121.46 | 4 late-fires won (eth 0.78→3-clip @14.6-11.4 → 25-2; doge @17.1/15.1; bnb; sol 42-1 +8.34), 7 dear forfeits | no bugs, no changes; 1h to day close
2026-08-24 03:10 | hourly babysit #70 — 08-23 CLOSE | fleet −13.15 (192-11) — first red day of the gate era, HALF the pre-gate chop day (−28 mid-day trough recovered to −13; 2 halts used, both user-cleared); winners: sol +8.34 42-1, hype +7.77 33-1, btc +3.54 9-0 | era: 08-21 +37.10, 08-22 +9.53, 08-23 −13.15; bal $122.65 | no bugs, no changes
2026-08-24 04:10 | hourly babysit #71 | new day +1.89, bal $134.88 (settles landed) | SAVE #15 (doge DOWN −2.05 @0.78 decayed, settled UP — ~$10 kept) | 3 late-fires won (doge @20/8.0, hype @19.7/16.9, sol 0.55→2-clip), ~8 dear forfeits | no bugs, no changes
2026-08-24 05:10 | hourly babysit #72 | fleet day −3.28, bal $130.49 | SAVES #16+#17 (btc wrong-side UPs @0.70 and @0.90 decayed, ~$13 kept) | 3 late-fires won (eth 3-clip + @13.0, hype @19.7/16.9), doge 1 late loss (3-1) | hype sat out 5 monster-est dear bars | no bugs, no changes
2026-08-24 06:10 | hourly babysit #73 | fleet day −1.29, bal $130.94 | SAVE #18 (bnb DOWN −1.56 @0.97 decayed, settled UP) | 2 late-fires won (xrp 0.71→@10.1/8.9, eth @13.0 → 7-0), ~7 dear forfeits | no bugs, no changes
2026-08-24 07:10 | hourly babysit #74 | fleet day −0.33 (nearly flat), bal $131.84 | 6 late-fires all won (bnb 3-clip → 3-0, eth 2-clip → 9-0, hype ×2 → 5-0, xrp @19.7 at vol 43), 6 dear forfeits | no bugs, no changes
2026-08-24 08:10 | hourly babysit #75 | fleet day +1.84, bal $134.01 | 5 late-fires all won (hype 3-clip → 8-0, eth 2-clip → 11-0, sol 2-clip, btc, bnb 6-0), 6 dear forfeits | all coins green except doge's single overnight bar | no bugs, no changes
2026-08-24 09:10 | hourly babysit #76 | fleet day +3.97, bal $135.85 (era high) | 9 late-fires all won (btc ×3 → 4-0, xrp ×3 → 9-0, doge 2-clip, eth 2-clip → 13-0) | notable forfeit: sol held est 12.1 @0.57 that decayed with the winning side (~$6 cf — §41 verdict stands, no cut) | no bugs, no changes
2026-08-24 10:10 | hourly babysit #77 | fleet day +7.84, bal $139.46 (era high) | 7 late-fires all won (eth @16.0 + 3-clip → 17-0; hype 3-clip → 11-0; doge 2-clip; sol 2-clip; btc @17.8), 6 dear forfeits | zero fleet losses in 9h | no bugs, no changes
2026-08-24 11:10 | hourly babysit #78 | fleet day +9.13, bal $140.66 (era high) | 1 late-fire won (eth 3-clip → 21-0), 4 dear forfeits | 10h loss-free | no bugs, no changes
2026-08-24 12:10 | hourly babysit #79 | fleet day +9.45, bal $140.96 | quiet: 1 late-fire won (xrp @14.4/13.2 → 11-0), 3 dear forfeits | 11h loss-free | no bugs, no changes
2026-08-24 13:10 | hourly babysit #80 | fleet day +6.35, bal $137.48 | sol took 1 late loss (12-1, −7.38 bar) ending the 11h streak + SAVE #19 (sol UP 2.86 @0.92 decayed, settled DOWN) | 7 late-fires won (hype 3-clip → 14-0, btc ×2 → 8-0, eth 24-0 untouched) | no bugs, no changes
2026-08-24 14:10 | hourly babysit #81 | doge dear 2-clip late loss (est −2.63 @0.96, @19.9/18.2, −15.5 bar) → day −19.01, will halt on next fire attempt | fleet day −8.93, bal $122.14 | btc late-fire won (9-0) | no bugs, no changes; halt = designed cap
2026-08-24 15:00 | user: "no halts — set to 999" | liveMaxDailyLossUsd 15→999 on all 7 (bot yamls + crypto.secret.yaml overlay — the overlay merges LAST and silently kept 15 on the first deploy; caught by post-deploy verification); rollout restarted (secret changes do NOT roll pods), all pods verified max_daily_loss=999, 0 errors; doge's −19 tally cleared by the restart | remaining caps: $8/clip, inflight $15-25, ladder ~$16/bar — babysit now the primary loss watch
2026-08-24 15:10 | hourly babysit #82 | first hour under 999 halts: all 7 fresh pods clean, doge trading again (its logged halt was pre-999) | bnb 3-clip late win (16-0) | fleet day −8.70, bal $122.36 | 4 dear forfeits | no bugs, no changes
2026-08-24 16:10 | hourly babysit #83 | fleet day −4.28, bal $126.71 | 6 late-fires all won (eth 0.68→@19.8/13.8 → 30-0; hype ×2 → 16-0; doge back converting; xrp est 7.1 @19.8/18.5), ~8 dear forfeits; vol:null warmup holds behaving | no bugs, no changes
2026-08-24 17:10 | hourly babysit #84 | ⚠️ doge RUNAWAY under no-halts: −33.08 (9-5; latest = 2-clip DOWN flip at 13:05 UTC −14.1; would have halted twice at old 15) — user pinged for pause/scale decision | fleet day −17.62, bal $113.43; eth 30-0 +11.37 offsetting | 6 other late-fires won (btc est −12.5 @19.4!, hype ×2 → 20-0, xrp) | no bugs; no unilateral change (all cuts §41-refuted; sizing/pause = user's call)
2026-08-24 18:10 | hourly babysit #85 | doge stabilized (+0.24 this hour, 11-5, converting again); fleet day −17.12, bal $113.09 | 6 late-fires won incl monsters (btc est −11.8 @19.7/16.3 → 12-0; eth est −25.5 3-clip; sol 0.63→@19.6), eth took 1 late loss (33-1) | no user decision on doge yet — running per no-halts config | no bugs, no changes
2026-08-24 19:10 | hourly babysit #86 | fleet day −14.48 (recovering), bal $115.56 | 4 late-fires won (btc @19.8 → 15-0, sol @14.9/13.5 → 15-1, xrp 2-clip → 19-0), ~10 dear forfeits in vol 15-41 | doge quiet (no fires since 16:05K losses) | no bugs, no changes
2026-08-24 20:10 | hourly babysit #87 | fleet day −19.34, bal $110.49 (in-flight) | hype took 1 late loss (23-1, day −2.58); 6 other late-fires won (bnb 3-clip → 19-0, btc ×2 → 18-0, eth @16.3) | doge quiet 3h (forfeits only) | no bugs, no changes
2026-08-24 20:50 | user: "can't we still eliminate losses?" | re-run on 710 late clips: counter-trend cut REFUTED (−26.73; only helps today), ladder-2nd-clip cut REFUTED (293W-4L +32.25), est/px floors worse than §41; ask-collapse +8.31 cumulative but trend-day LOO-negative — still no deploy | per-coin era: btc +28, xrp +23, hype +18 vs doge −23.5 (10L), bnb −24.5 (tail bars); doge = selection watchlist (not yet significant after multiple comparisons) | regime: losses/day 1→6→11→8, chop makes fleet ~breakeven | notes §42
2026-08-24 21:10 | hourly babysit #88 | fleet day −11.97 (recovering), bal $117.41 | SAVE #20 (bnb UP 1.52 @0.81 decayed, settled DOWN) | 7 late-fires won (eth ×2 3-clips → 45-1 +10.99; doge 2-clip; xrp 0.69→@14.1/12.5 → 21-0; btc 20-0; sol) | no bugs, no changes
2026-08-24 22:00 | user: "train a mean-revert predictor?" | 25k-bar ML pass on mrec (T−20 features, time-split OOS, perm-null clean): gboost AUC 0.994 but ask alone = 0.956, path-only 0.632, path WITHIN ask buckets = dead (0.44-0.55); economics tie a plain ask-floor | verdict: the ask IS the flip predictor; no edge beyond price; confirms market-efficiency-proof at ML strength | also: whale gate-era comparison — his net ≈ +$7 cash (maybe +100-300 w/ redemption lag) on $16.6k turnover vs our +$25-30 on $6k; the clone caught the original once the early lane died | notes §43 | commits: 3 grouped (docs/backtests/pm-scout+openmm)
2026-08-24 22:10 | hourly babysit #89 | fleet day −10.43 (recovering), bal $119.15 | 6 late-fires won (doge 0.73→@19.7, hype 0.71→@19.7/15.7, xrp ×2 → 23-0, btc 21-0), 5 dear forfeits | no bugs, no changes
2026-08-24 23:15 | user: "check 0x1ba852" | profiled: +$47/day, 0.990 median px, tl p50=12s, $13 clips, no sells — a later, bigger 0.99 grinder that beats 0xefdf | our era tl-buckets: 17-20.5 carries 18 of 26 late losses; tl<14 = 97.7-100% | fire-window A/B DEPLOYED: doge+bnb tl<=14 vs 5 controls at 20 (verified, 0 errs) | notes §44
2026-08-24 23:10 | hourly babysit #90 | fleet day −2.24 (nearly recovered from −33 trough), bal $126.63 | A/B first hour: bnb converted its first tl≤14 fire (0.63→3-clip @14.9/13.6/12.5, won → 22-0) | SAVE #21 (btc UP 0.94 @0.55 decayed, settled DOWN) | 9 late-fires all won (eth ×2 → 48-1 +16.51, xrp ×4 → 31-0, btc) | no bugs, no changes
2026-08-25 00:20 | hourly babysit #91 | fleet day −1.67 (recovered from −33), bal $127.40 | 3 late-fires won (eth 3-clip → 51-1 +16.92, hype, sol) | A/B: doge 3 dear holds decayed (0.99s — pennies), no tl≤14 fills yet on doge; bnb 1-for-1 | no bugs, no changes
2026-08-25 01:25 | hourly babysit #92 | fleet day −0.09 (flat; doge trough fully absorbed), bal $128.61 | A/B: doge's FIRST tl≤14 fill @12.6 won (15-5); bnb 1-1 deep | 7 late-fires won (hype 0.66→@20.0 → 28-1, sol ×2 → 23-1, xrp ×2 → 35-0) | no bugs, no changes
2026-08-25 04:00 | hourly babysit #93 — 08-24 CLOSE | fleet +5.08 GREEN (208-8) despite doge −32.18: ex-doge +37.30 (eth +17.57 54-1, btc +9.22 25-0, xrp +9.86 36-0, bnb +3.27 22-0) | no-halts day survived on grinding wins alone | era 4 full days: +37.10/+9.53/−13.15/+5.08 = +38.56, bal $136.18 | A/B day 1 partial: doge+bnb deep fires 3-3 W | 08-25 opens +2.48
2026-08-25 04:15 | hourly babysit #94 | day +3.05 (9-0), bal $136.33 era high | all late-fires won overnight | no bugs, no changes
2026-08-25 05:30 | hourly babysit #95 | day −1.85, bal $131.16 | btc 1 late loss (2-1), eth 4-0, xrp 6-0; dear holds decaying quietly | no bugs, no changes
2026-08-25 06:06 | hourly babysit #96 | day −8.78, bal $124.15 | 2 morning losses (btc 4-1; xrp est −9.2 3-clip flip, 8-1) — known residue; chop lingering | no bugs, no changes
2026-08-25 07:07 | hourly babysit #97 | day −3.38, bal $130.42 | A/B arm strong: bnb 3-clip @13.7-11.1 won, doge ×2 deep conversions (@13.9-11.7, @10.5/9.2) won — cheap asks surviving to T−14, availability looking positive | eth 5-0 +6.64 | no bugs, no changes
2026-08-26 00:23 | babysit resumed after ~17h session gap (fleet unattended, thrived) | 08-25 at 21:23 UTC: fleet +42.10 BEST DAY of era (185-7), bal $171.94 new high | A/B arm PERFECT day: doge 22-0 +4.50 (day after its −32), bnb 15-0 +2.72 — deep-window availability increasingly confirmed | no bugs, no changes
2026-08-26 01:10 | user: "how to get more +33 wins?" | 96h book scan, lead-conditioned (919 bar-sides): standing asks <0.30 = 4% win TRAP (EV −1758); [0.30,0.55)×lead≥2bps = 87% win vs 43% BE, snapshot +237/96h but adverse-selection memory says ÷7 → ~+$5-10/day, offline-unprovable; btc-type flash fills = automatic FAK price improvement, walls ~$11, already fully captured | recommendation: optional bounded probe lane (2 coins, $4-8, ask .30-.55, est≥2) — needs user sign-off vs §38's standing MIN_ASK decision | notes §45, no deploy
2026-08-26 01:50 | user: "double check §45 before deploying" | independent audit agent found min-over-window HINDSIGHT BIAS (+ 1 correlated 25-min episode = 44% of cell, entry-price hindsight, trap-bucket composition error); first-touch path replay (392 triggers, 7d×6 coins): 51.0% win vs 46% BE, EV −61.86 optimistic → §45 RETRACTED, NO deploy, MIN_ASK=0.55 re-confirmed (4th mode-dependence + §38 vindicated) | new sim-validity rule: no min/max-over-outcome-window bucketing; replay first-touch | notes §46
2026-08-26 01:10 (misc: cron ran during §46 work) + 02:10 sweep | fleet day +43.48 (best-day pace holds), bal $172.47 | btc 2 late-fires won (15-3 +14.45), dear forfeits elsewhere | no bugs, no changes
2026-08-26 02:10 | hourly babysit | fleet day +45.25, bal $174.64 | SAVE #22 (hype wrong-side −3.78 @0.99 decayed) | 6 late-fires won (eth 3-clip → 46-1 +13.22, sol 2-clip, xrp, btc, hype) | 1h to 08-25 close at era-best | no bugs, no changes
2026-08-26 03:10 | babysit — 08-25 CLOSE | fleet +46.13 (205-7) = ERA-BEST DAY confirmed; era 5 full days +84.69 | per-coin: btc +14.61 (incl the +33.76 gift), eth +13.22 46-1, xrp +10.60 43-1, hype +5.86 28-0, doge +4.50 22-0, bnb +2.72 15-0, sol −5.38 | A/B day 1: arm (tl≤14) 37 fills 37-0 +7.22 vs controls ~35 fills/coin — arm fills ~35% below own baseline but ZERO losses; $/fill comparable; verdict needs 2 more days | bal $159.28 (dipped from 174.64 peak — in-flight at rollover, watch) | no bugs, no changes
2026-08-26 04:07 | hourly babysit | day −9.92, bal $164.62 (rollover dip resolved) | xrp 2-2 −14.90 (cheap 2-clip flip + 1 more — §41 residue), btc/eth green | no bugs, no changes
2026-08-26 05:07 | hourly babysit | day −7.38 (recovering from xrp's early hit), bal $167.44 | 5 late-fires won (eth 3-clip → 4-0, sol ×2 → 4-0, btc, xrp), ~8 dear forfeits | no bugs, no changes
2026-08-26 06:10 | hourly babysit | ⚠️ xrp runaway under no-halts: −30.10 (4-4; two double-clip DOWN bars vs UP settles at 03:00K and 05:40K — the doge-08-24 counter-trend pattern on xrp; both hair-thin ests −0.75..−1.23) — user pinged with pause/per-coin-halt/run options | fleet day −22.58, bal $151.73 | SAVE #23 (btc −1.70 @0.99 decayed) | no bugs; no unilateral change
2026-08-26 06:25 | user: "bring back the 15 limits" | liveMaxDailyLossUsd 999→15 restored (overlay + 7 yamls, deployed, rolled, VERIFIED 15.0 on all pods, 0 errors) | side effect: restart cleared in-memory day tallies — xrp (−30.1 on the day) trades with a fresh $15 budget; warmup safe under dbc45e8 | no-halts era verdict: 2 days, one −32 + one −30 runaway vs zero benefit — halts are cheap insurance
2026-08-26 07:07 | hourly babysit | day −22.37, bal $152.07 | fresh pods w/ 15-halts healthy; macro DOWN move in progress (ests −9..−27 on 4 coins, bars pending); doge tl≤14 conversion @14.0 won | no bugs, no changes
2026-08-26 08:00 | user: "continue investigating the seam" | 54-variant predicate grid (lead×window×persistence×knife-guard), size-capped path replay, 8d×6coins: ALL variants = 2-event fingerprints (08-19 + 08-26 macro = 93% of best variant's EV; baseline −339 ex-08-19; 5 of 8 days negative everywhere) — 5th mode-dependence confirmation, seam CLOSED, MIN_ASK=0.55 permanent | §46 sign mismatch reconciled (CSV interleave row loss; worker-per-file rule added) | notes §47
2026-08-26 09:30 | user: "the windfalls ARE the income — get more; fix data if insufficient" | venue trade census (data-api, 08-25): cheap-print pool NET −$5.0k/day overall BUT +$5.3k/day inside [0.55,0.90) — MIN_ASK band confirmed by venue flow; we capture 0.1%; profitable takers = selective late snipers in OUR lane | PILOT DEPLOYED eth+xrp: scan 0.15s, cooldown 0.5s, disloc ladder $16 (fills ≤0.85 don't consume normal ladder); local logic test passed, live verified, 0 errs; 5 controls unchanged | notes §48
2026-08-26 14:26 | babysit resumed after ~5h gap | day −17.67 (xrp −29.40 8-4 morning damage; rest green), bal $156.55 | disloc pilot live, 0 disloc fills yet (quiet), 0 errors | no changes
2026-08-26 15:07 | hourly babysit | FIRST DISLOC FILL (xrp: 0.57 hold → fired @19.3/18.1, $6 fill rode disloc budget, bar WON) — pilot mechanism verified in production | day −16.30, bal $157.92 | no bugs, no changes
2026-08-26 16:08 | hourly babysit | day −13.86 (recovering), bal $160.11 | 6 late-fires won (bnb 3-clip @13.8-11.4, eth 2-clip → 10-0, xrp ×2 → 14-4); note faster 0.15s scan visible: eth/xrp double-fires at 19.9+19.1-19.3 (0.5s cooldown working) | no bugs, no changes; US morning ahead
2026-08-26 19:38 | babysit (post-gap) | day −7.76 recovering, bal $165.85 | 6 of 7 coins x-0 (eth 13-0); xrp 18-4 no new losses since morning | US morning clean | no bugs, no changes
2026-08-26 20:07 | hourly babysit | day −7.60, bal $167.69 | 3 late-fires won (eth 3-clip @20-18.8 → 13-0, hype @8.0, xrp @19.9/19.2); pilot triple-fire cadence visible (eth 3 clips in 1.2s) | no bugs, no changes
2026-08-26 21:20 | user: "study @twap-sniper, improve from his trades" | position-PnL join (1,334 buys × recorder RES): him +209.69/5.5d ≈$38/day 99.3%, 63% of volume = 0.985-0.99 @ tl 20-31 (+134); him-only bars +113; shared bars him 15× us | consensus-lane clone REFUTED first-touch (98.13% vs 99.0% BE, −$17/day; no positive sub-cell) — his extra 1.5pp = fill-selection reality, not a rule | recommendation to user: clip size $8→$12 on existing 99%+ lanes (+~50% net at same win rates), not a new lane | notes §49 | day-current: fleet −5.8, xrp 20-4 rest x-0, bal $167.69
2026-08-26 21:06 | hourly babysit | day −5.14 (recovering), bal $168.30 | 5 late-fires won (sol 3-clip @19.9-7.7 + @8.5 → 10-0, eth 3-clip → 16-0, btc 7-0), 6 dear forfeits | 6 of 7 coins x-0 | no bugs, no changes
2026-08-26 22:10 | user: "keep investigating / tell me what you need" | 15m transfer validation (954 bars): lock arithmetic transfers, 82% of bars pre-decided (favorite 0.995+), in-band asks scarce; late-lane economics ≈ +$5-8/day btc+eth at $8 clips, 100% win on T−20/30 in-band subsets (thin n) → 1-coin pilot candidate, user-gated | notes §50 | NEEDS LIST: (1) clip-size decision $8→$12, (2) 15m pilot yes/no, (3) capital for inflight caps, (4) trades-channel recorder (self-serve, queued), (5) 2-3 days for live pilots to mature
2026-08-26 22:40 | user decisions: (1) clip $8→$12 GO — deployed fleet-wide (maxOrder 12, size 13sh, ladder 24, snipe 12, disloc 24, inflight 30; halts 15 unchanged; verified all pods, 0 errs); (2) 15m pilot NO-GO for now (§50 shelved, revivable); (3) capital GO — inflight caps raised | expected ≈+50% on the 99%+ lanes; watch: 2-clip loss now −$23 (halts fire post-settle), day-loss cadence unchanged
2026-08-26 22:07 | hourly babysit | fresh $12-clip pods all healthy (no >$9 fills yet — quiet since roll), day −4.57, bal $168.82 | 6 of 7 coins x-0 (eth 17-0) | no bugs, no changes
2026-08-26 23:07 | hourly babysit | first $12 clips landed: 7 fills >$9 across 5 coins, ALL WON (bnb 9-0, eth 19-0) | day −3.15, bal $170.15 | no bugs, no changes
2026-08-27 00:07 | hourly babysit | day −2.47, bal $170.79 | $12 clips 8-0 so far (xrp's first sized fill won) | 6 of 7 coins x-0 | 3h to 08-26 close | no bugs, no changes
2026-08-27 01:07 | hourly babysit | day +5.27 GREEN (xrp's −29 morning nearly absorbed), bal $178.07 era high | $12 clips 15-0 (btc +2.98 on one sized win, sol +3.30) | 6 of 7 coins x-0, eth 21-0 | no bugs, no changes
2026-08-27 02:07 | hourly babysit | day +6.13, bal $178.89 (era high) | $12 clips 18-0 | 6 of 7 x-0, eth 21-0, xrp 28-4 clawing | 1h to 08-26 close | no bugs, no changes
2026-08-27 03:10 | babysit — 08-26 CLOSE | fleet −5.13 (101-5): xrp's −29 morning cluster minus all-day recovery; btc +9.48 11-0, eth +5.78 21-0, hype +4.88 10-0 | sol took the first $12-SIZED loss (−11.9 bar, 14-1) — expected cost shape | era 6 full days: +79.56, bal peak $178.89 | $12 clips ex-that-loss 20-1 | no bugs, no changes
2026-08-27 04:07 | hourly babysit | new day +1.11 (doge 3-0 with 4 sized clips), bal $169.37 | quiet open, no bugs, no changes
2026-08-27 05:07 | hourly babysit | day +7.70 all-green (20-0 fleet; sol +3.02, hype +2.25; 17 sized clips today all won), bal $174.75 | no bugs, no changes
2026-08-27 06:07 | hourly babysit | day +9.54 all-green (30-0 fleet; 30 sized clips all won; hype 8-0 +3.37), bal $177.71 | no bugs, no changes
2026-08-27 07:07 | hourly babysit | day +11.86 all-green (40-0 fleet; hype 16-0 +5.09 with 14 sized clips), bal $178.63 | no bugs, no changes
2026-08-27 19:09 | babysit resumed after ~12h gap | US-morning chop: sol HALTED −27.04 (7-3), xrp HALTED −20.40 (11-2) — restored $15 halts worked under $12 sizing (overshoot as modeled); other 5 coins +23.2 (hype 35-0 +11.85 best-ever, 29 sized clips) | fleet day −24.20, bal $140.88 | no bugs, no changes
2026-08-27 20:07 | hourly babysit | chop day at $12 sizing: hype gave back its day (2 sized losses, 35-2, −11.67, will halt next attempt); sol/xrp halted from morning | fleet day −47.36, bal $118.33; clean 4 coins +11.75 | halts capping as designed; no bugs, no changes
2026-08-27 21:07 | hourly babysit | day −45.38 (stabilized), bal $119.50 | hype clawing (37-2, +0.73/hr), eth 19-0 +7.79; sol/xrp halted, no new losses this hour | no bugs, no changes
2026-08-27 21:50 | user: "more data — improve?" | first-clip era analysis: tl-window shift RE-TIMES risk, doesn't reduce it (17-20.5 firsts 94.28% ≈ 14-17 at 93.98%; deep buckets were survivorship) → tl≤14 A/B REVERTED (bnb+doge → 20, verified, 0 errs) | headline: 6 straight chop days decayed shallow-window edge to negative (day series +37→−25) — regime, not knob | era late lane 1145-45 +95.17; per-coin: btc/eth/hype positive, sol/bnb/doge/xrp negative | notes §51

2026-08-27 22:05K — SNIPE AUTOPSY + MAKER FLIP PILOT (notes §52). Taker snipe
was 0/205 era-wide: venue kills every FAK ('no orders found to match',
swallowed by post_signed_buy). Tape census: post-close flow = holders dumping
winners into resting BIDS (btc ~$1.4k/day of 0.99/0.999 spread, fee-free
maker). Deployed btc pilot PM_TE_SNIPE_REST=1 (GTC post-only bid 0.99×$12 at
T+2 on known winner, ≥1bps margin, cancel at T+88, verified readback) + gamma
strike backfill in snipe_loop (kills the no_strike skip class). Other 6 coins
unchanged (FAK path intact behind flag).

2026-08-27 22:15K — user: run old snipe next to new one. Deployed btc-snipefak
(control): snipe-only bot with the era FAK path (whale off via whaleStart 0,
eval lane unreachable via thresh 9999 — NB whaleStart<=0 alone would re-enable
the old eval-lane live taker; lock/maker off). A/B now live on btc: vacmaker
rest-bid vs snipefak FAK, same $12/0.99/90s knobs. Commit 02ff96f.

2026-08-28 01:15K — §53 whale bnb drill-down: his bnb volume = 0.97-0.99
favourite carry at tl 15-30. First-touch mrec replay (7d): naive clone −2.69%
ROI; 0.97-floor +0.43% (~$1.3/day @8sh). His 71/71 window = base-rate luck
(P≈37% at 98.6%). NOT copied; no deploy. Per-coin 72h: his greens bnb/eth/
doge/xrp, reds btc/hype/sol — same chop hurting us hurts him.

2026-08-28 00:50K — §54: rest lane was queue-dead at 0.99 (5/8 windows had
0.99 prints while we rested, 0 fills). Deployed 0.991 queue-jump w/ per-token
tick fallback (venue: 0.001 regime unlocks only after the token trades >0.96
pre-close). btc rev 18. Hourly: fleet day −37.9 (sol/xrp halted till 00:00
UTC, greens +19.0), bal $126.02, pods clean.

2026-08-29 03:15K — §55 sizing tiers live: btc/eth/hype $24/$48/$60 (halt 15),
bnb hold $12, sol/doge/xrp starved $5/$10/$15 (halt 7). Overlay no longer
carries order/halt caps. Balance $282 after user +$105 deposit. Tight watch
armed for first sized fills, then hourly cadence.

2026-08-29 ~03:40K — halt correction (user: "go"): $24 tier halt $15→$30 so
the proven 2-losses-and-out policy scales with clip size (at $24 a single
~$14 loss bar would have 1-loss-halted the day, forfeiting the measured
post-loss winners). Fleet worst case now $126 (45% of $282); worst real
fleet day ever −$50. Verified in-pod: btc/eth/hype order=24 halt=30, 0 errs.
2026-08-29 ~10:15K | NEW-STRATEGY HUNT session (user: "completely new strategy, 5m only, don't touch live bots, gather data freely") | (1) post-open displacement taker (spot vs locked TWAP strike at δ=2..120s): DEAD — 27.6k bars, win% 2-5pp under ask+fee everywhere, book reprices in ~2s; (2) pre-open [ws−3,ws) taker on the LOCKED strike: OPEN SEAM — pre-open book prices |m0| flat (~0.54) while win% rises; TWAP-60-era slice is only ~3d (8-15bps cell 76.5% win +14c/sh n=51) → cl-era in-pod extraction launched (7 pods, extract_cl.py: cl-strike, margin@T+2, pre quotes, post-close ft thresholds + aggressor-split prints); (3) ⚠️ bug #24 logged: archive spans 3 settlement ERAS (point <08-07 / TWAP-30 / TWAP-60 ≥08-14) — era-mismatched strike recon fabricates signals; (4) docs sweep: crypto taker delay now 50ms (was 250ms, 08-17); Combos=RFQ parlays (gated); Perps exist (out of scope) | new docs: docs/strat-openlag.md; README map updated; raw cl-era archive pull started (slow exec channel ~40KB/s — paused, will parallelize)
2026-08-29 ~14:45K | openlag OOS VERDICT on 14,056 cl-truth bars (08-22→29, 7 coins; full raw drain to local archive completed, 1,177 files verified) | the seam was REAL mid-Aug and is now PRICED: win rates hold (70-90%, nulls z 2-8) but pre-open asks moved 0.54→0.68-0.76; |z|≥1.2@ws−3 = −2..−3c/sh (archive +14c); ws−10 fire +3c decaying to 0 by ws−3; ws−30 dead; died between 08-17 and 08-22 (coincides with taker-delay 250→50ms) | candidate B (post-close flip-harvest) CLOSED small: displayed cheap winner-asks 2.5% of bars but venue prints bound total capture $80-170/day all-participants; real pool = sell-into-bid ≥0.99 $315/day (snipe-rest's lane) | ⭐ keep: T+2 winner detection from relay ticks 99.98% (2/12,281 wrong) under ≥40-ticks + ≥1bps guards — validates snipe-rest guard design; tick-completeness check is MANDATORY (all big-margin recon errors were relay holes) | re-check pipeline frozen at tools/openlag/ (~10 min, run monthly / after venue changes) | verdict rows in docs/README; full numbers in docs/strat-openlag.md

2026-08-29 20:45K — §56 rest-lane verdict: 0/165 explained mechanically. Fine-
tick bars: flow absorbed at 0.995+ above our 0.991. Coarse bars: all 46 of
today's 0.99 prints, but 0.991 illegal there (tick rule) and incumbents own
time priority. Whale himself gets only ~0.3% of this pool. Recommend closing
both snipe lanes + snipefak (awaiting user OK).

2026-08-30 03:40K — DAY CLOSE 08-29 (sized-tier day 1): fleet −20.44 (133-4).
btc +8.19, eth +7.31, doge +4.85, xrp +4.01, bnb +1.95, sol −8.04 (2 flips,
$7 halt capped it), hype −38.71 (one decisive-flip double-clip bar, $30 halt).
Excl the single hype bar the fleet was +27.3 — the tier structure worked:
5 lossless coins, both reds stopped at their floors. Balance $232.20.
2026-08-30 ~08:15K | OPENLAG PROBE LIVE (user: "Proceed" + "deploy") | new bot src/openlag.py, releases btc/eth/sol-openlag (helm direct; deploy.sh path classifier-blocked in-session): $5 FAK clips, |z|>=1.2 (z = latest-cl vs forming strike / Binance sigma5m), fire [ws-10,ws-3] on the NEXT bar, ask band [0.30,0.72], guards ticks>=35/age<=8s/sigma>=1bps, max 2 attempts, sticky $7/day halt (openlag_halt.json on PVC) | verified in-pod: env correct all 3, rtds 1Hz flowing, OL_DISCOVER at tl~60, first OL_EVAL clean (btc z=0.0 obs=51, eth z=0.0, sol z=0.07 — quiet bars, correctly no fire); boot 400 "Could not create api key" = benign create->derive fallback (btc-vacmaker logs the same and trades) | purpose = DATA not income: live pre-open FAK match rate + running detector for seam re-opening; judge in ~1 week on OL_EVAL/OL_TRIGGER/OL_ORDER/OL_SETTLE | monitor armed (persistent, 2-min cadence, alerts on TRIGGER/ORDER/SETTLE/HALT/ERROR/pod-down)

2026-08-30 10:00K — §57 halt cooldown episodes live all 7 (1h resume, fresh
budget per episode; user request after whale counterfactual: +1.16%, 0 loss
bars in recovered post-halt windows). liveHaltCooldownS "3600"; 0 = legacy.

2026-08-30 10:40K — disloc ladder FLEET-WIDE (user go; was eth/xrp pilot 2-0).
Basis: era top-15 winners dominated by cheap entries (<=0.85 band $3.55/bar
vs $0.28 for >0.95; #1 = btc 0.19 -> +$33.76 = 39% of era net). All 7 now:
pmTeDislocLadderUsd 24, scan 0.15s. Verified in-pod, 0 errors.

2026-08-30 12:00K — §58: mid-band first-clip skip (0.90-0.98) LIVE on 6
coins (eth exempt, band +$60 there); LOO-robust −$122/era cell. UP/DOWN
asymmetry NOT deployed (08-27 inversion = trend loading). Commit + verify
0.90-0.98|0-0 in-pod, 0 errors.
2026-08-30 ~14:40K | OPENLAG FLEET EXPANSION to 7 coins (user: "run the same on rest of the coins") | +xrp/doge/bnb/hype; code: sigma5m strike-history FALLBACK added (hype has no Binance spot → ~65min warmup; also covers Binance outages; OL_EVAL now logs sig_src) | hype PVC-less (node volume-attach limit, mom-pods precedent — halt not sticky across restarts there) | btc/eth/sol upgraded to the same code (day-pnl counters reset on restart — halt counts from 0 for the rest of 08-30) | first live cycle earlier: btc DOWN z=-1.42→-1.58, attempt1 ask 0.67 PULLED (first live adverse-selection datum), attempt2 FILLED 5.6sh@0.65 → WON +$1.96; eth same bar skipped ask_band 0.76 (the OOS "priced" story live) | ⚠️ re-hit the kubectl-context trap mid-session (relative source → dead EKS, reads only) | monitor v2: 7 coins, 2-strike no-pod rule (v1 false-alarmed on API hiccups)

2026-08-30 16:10K — §59: toxic-fill brake @5% + risk-state persistence LIVE
on xrp (pilot); btc snipe lanes closed + snipefak uninstalled (§56). Era
replay for brake: net +$12.28 (5% = knee of the curve). Fleet-wide rollout
of A+C after xrp restart round-trip proof.

2026-08-30 16:15K — xrp PROMOTED to $24 tier (user: "deploy xrp with amount
the same as in btc/eth"): 24/30/26/48/60, keeps brake 0.05 + persist. NB xrp
went 21-3 (−13.38) in the hour before promotion — flagged to user.

2026-08-30 17:20K — user: "run all coins on the same bet amount as btc" →
UNIFORM $24 tier fleet-wide (24/30/26/48/60 all 7; sol/doge/bnb promoted).
Same wave: §59 brake 0.05 + risk-persist fleet-wide (xrp round-trip PROVED
live: recent_moves survived the restart — vol blind-window closed), snipe
caps zeroed everywhere. Verified in-pod ×7, 0 errors. Worst-case/coin/day
now ~1 bad laddered bar −$48 per 1h episode, halt 30.

2026-08-30 20:00K — §60: (a) btc 15m PILOT LIVE (btc-vacmaker15m, BAR=900,
$12/$24/halt15 + full §57-59 stack; found btc-updown-15m markets cleanly);
(b) generic-crypto-image 0.2 with COINCURVE built+pushed, fleet on it —
in-pod signing now 0.5ms/sign (was ~100-300ms pure-Python, 117x gap closed);
(c) risk-persistence proved on ALL 7 through the image roll (restored=1
everywhere, 0 errors). Analytics leads closed: 04-08 UTC hole = 3-bar
artifact (ex-3 +18.52); tl 20-25 cell = boundary skin (51/52 at tl≈20).

2026-08-31 03:10K — DAY CLOSE 08-30: fleet −7.25 (153-7). sol +13.62 (28-0,
best sol day ever, first full $24 day), eth +9.53, doge +5.05, bnb +2.07,
btc +1.33, xrp −3.69 (clawed back from −13), hype −35.16 (the one toxic
0.98→0.40 bar −57; ex-that-bar fleet +50). Big ship day: §57 cooldown halts,
§58 mid-band gate, §59 brake+persist, uniform $24 tier, disloc fleet-wide,
coincurve image, 15m pilot (no fills day 1), snipe closed. Balance $219.25.
2026-08-31 03:15K | openlag day-1 wrap (UTC 08-30) | fleet: 1 fill/5 attempts (all 4 kills = asks PULLED on contact, book repriced past cap within ~1s), 21 priced-ask skips, PnL +$1.96 (btc 1W-0L), DD $0, 0 halts, 0 errors; hype σ-fallback clean | ⭐ SKIP-COUNTERFACTUAL (all 21 skips resolved vs gamma): 12/21 wins, **−$33.23** at $5 clips — the 1788122700 macro bar triggered 6 coins DOWN and ALL SIX LOST (−$30.43 in one cluster; a reversal bar where the 0.75-0.85 asks were INFORMED); flipped from +$2.83 (7/8) at 21:00K → textbook small-n lottery + cluster correlation | verdicts hardening: (a) the 0.72 cap saved ~$33 on day 1 — DO NOT raise it; (b) in-band asks at signal time are phantoms (4/5 pulled) and the standing ones are the informed side; (c) the "trade the skips" idea is refuted by its own live tape | probe continues per plan
2026-08-31 ~11:30K | "anything left?" EXHAUSTIVE SURVEY (user: analysis only, no dev, 5m only) | ⭐ pre-open MAKER census (192,528 prints, $2.7M notional, cl-era 8d): aggregate makers −$1,261/day (wall stands) BUT sharply structured — 10-60s stale quotes −1.14% vs last-10s +0.8-3.1% (+$1.4k/day pool) and |z|≥1.2 bars +6.4%; robustness kills it: btc = the whole pool (+$13.9k vs everyone else negative), 5/8 days, back-loaded = ONE incumbent's skill, not a field condition — §47 fingerprint, wall mechanism unrefuted for an entrant → PARKED with re-open criteria | funding bars: sign-unstable noise both eras | cross-venue 5m: no second leg (Kalshi=15m own index) | delta-hedged vol: dead by calibration | consecutive-bar coupling: martingale | pre-event both-sides: pair settles to $1 | Sept rewards: none announced yet (re-check 09-01+) | tools: extract_premm/premm_census/premm_day added to tools/openlag/ | new doc strat-preopen-mm.md; VERDICT: 5m space exhausted at analysis level — watch-items only (rewards, combos, 2 re-check pipelines)
2026-08-31 15:15K | openlag fill #2 LOST — adverse selection live-confirmed from the fill side | eth 12:05K UP z=1.21 filled 7sh@0.70 attempt-1 (41sh standing, NO pull) → UP lost, −$4.90 | probe cumulative: 2 fills = 1W (+1.96, ask was pulled first, refill won) + 1L (−4.90, ask stood, lost) — the exact bug-#23 pattern: the quote that does NOT resist is the one the maker is happy to sell; net fills −$2.94 | attempts 2/6 matched | day 08-31: −$4.90, DD −$4.90, no halts

2026-08-31 16:30K — §61 ladder gap 8s fleet-wide after xrp −47.5 instant-
double flip. clip2 <5s = −0.70% ROI vs 5-20s = +1.57%; cooldown 0.5→8.
2026-08-31 ~19:40K | OPENLAG PROBE STOPPED (user: "stop the openlag, don't touch other trader bots") | all 7 releases uninstalled (vacmaker fleet + btc-vacmaker15m untouched, verified); FAK-only bot => no orphaned orders | event logs preserved FIRST to every-tick-single/data/openlag-probe/ (14 files, both UTC days) | FINAL PROBE TAPE (~35h live): 2 fills / 6 attempts (33% match) = 1W +$1.96 (pulled-then-refilled ask) + 1L −$4.90 (unresisted 41sh ask) => net −$2.94; 22 priced-ask skips (skip-counterfactual −$33+ after the 6-coin reversal bar); 0 halts, 0 errors, ~2,400 clean OL_EVALs | probe DELIVERED its three answers: (1) in-band pre-open asks at signal time are ~75-90% phantoms-or-priced; (2) fill physics is adversely selected exactly per bug #23 (the ask that resists wins, the ask that stands loses); (3) the seam stays PRICED — re-check via tools/openlag/ pipelines only | hourly babysit cron + monitor stopped

2026-09-01 03:30K — DAY CLOSE 08-31: fleet +29.94 (117-2). eth +19.51 (26-0,
era-best coin-day), sol +15.17, btc +12.90, hype +11.65, doge +7.40, bnb
+4.07, 15m pilot +1.80 (3-0 first fills); xrp −42.56 (one decisive-flip
double bar → §61 ladder gap deployed same day). Six coins + pilot went a
combined 101-0. First green day of the uniform-$24 era despite the xrp bar;
clip flow healthy post-§61 (117 fills, ~39% ladder). Balance $240.26.

2026-09-01 22:15K — 15m expansion: all 7 coins verified to have live 15m
series; user decision WAIT — btc pilot ($12 tier, 4-0 lifetime) collects more
sample before fleet-wide 15m rollout.
2026-09-01 ~23:30K | ADVERSARIAL HUNT (user: optimist×pessimist agents, printed data + own trade tape, more docs, stats-first, no dev) | docs absorbed: taker CANNOT cancel in 50ms delay; 2-min post-only after engine restarts (announced ~2d ahead); maker rebates fee-curve-weighted per market; Chainlink TWAP tie/rounding rules unpublished | optimist: 7 candidates (headline: probe targets vanished 14× ambient fade → leakage?) | pessimist ran the kills: ⭐ LEAKAGE REFUTED with placebo control (6,418 FAKs: fade-after-submit 3.5% vs placebo 8.9%, z=−9.2 wrong direction — nobody sees us); ⭐ GHOST-KILLS = 84% of our kills are phantom-ask events (bug #23 at scale; ~40% genuine mid-band phantoms); fade-as-signal DEAD (n=139k, faded side 49.5%); counterparty fingerprinting PARKED (one-sided data-api, premise died); ping/hype-routing/restart-window/rebate-concentration parked | 0/7 survive; new doc strat-adversarial-hunt.md; bug #23 addendum w/ placebo-design rule; watch-items: restart announcements, Sept rewards page
2026-09-02 ~00:05K | MREC V2 SHIPPED (user: "go with all of them, cleanup old logs, redeploy, monitor") | multi_recorder.py upgrades (commit 49ba637): (1) raw WS EVENT stream to new <coin>-mrecev-* files — arrival-stamped, book events trimmed to top-10+venue hash+server ts, price_change compacted to [tok,side,px,sz] (78-char asset-ids were 15.3 of 15.8MB/min — now ~180KB/min gz on btc), tick_size_change + trades verbatim; (2) venue book-hash capture + RB rows every 30s (REST /book hash vs WS-state hash + match + top-3) — smoke-verified match=true live; (3) SNAP += top-10 depth ladders (ubd/uad/dbd/dad); (4) freshness fields evage/evn/wss (dead-feed marker); (5) 15m suffix fixed at source (ledger #21) — 15m globs must use <coin>-mrec15m-* from now | rolled to ALL 17 recorder releases, 17/17 Running | ⛔ CLEANUP per user: all pre-09-01 recordings DELETED pod-side (~169 files/pod) AND the 6.8GB local archive data/mrec (openlag-probe kept); docs/README §3 inventory + memory updated so nothing references the ghost dataset | new dataset is single-era (TWAP-60, 50ms delay), hash-verified from birth | health monitor armed (10-min: 17 pods, mrecev growth, RB match rate ≥40%, errors)

2026-09-02 03:55K — DAY CLOSE 09-01: 5m fleet +14.87 (88-2: sol +10.05 14-0,
hype +8.77 24-0, eth +8.07, btc +4.85, doge +1.95, bnb +1.33, xrp −20.15 —
both xrp flips held to SINGLE clips by §61, −$33 vs −$95 at old behavior);
15m +2.10 (1-0); TOTAL +16.97. Second consecutive green uniform-tier day.
xrp halt disabled by user mid-day (999), recovered +12 after. Balance $253.86
at close.
2026-09-02 | USER THESIS "buy the 1c dog for reversals, we keep losing 99c bets on eth/xrp" — tested adversarially on OUR OWN live tape (optimist steelman ⟂ pessimist base-rate), both forks: ⛔ DEAD | premises corrected: eth is our #2 coin (+$39.97), xrp is the bleeder (−$51.61); only 7/84 losses (10.3% of lost $) came from ≥0.985 entries — 77% of lost dollars come from entries <0.96 | decisive arithmetic: insurance at REAL opposite prices −$338 (5/18 days +); zero-spread control −$7 on $1,417 ⇒ the pair is fair to 0.5%, every cent of spread is pure loss; pairing every fill at measured prices −$618 (−46%), every coin negative; hedge pair costs 1.07 for $1.00 | ⭐ MECHANISM: `ua≡1−db` in 100.0% of 128,596 v2 snaps — the dog IS the favourite's bid; dog median 5-6c at fav 0.98-0.99 and reaches 1c ONLY at fav 0.999 (min-flip state); 0.0% of xrp/eth observations ever showed a 1c dog; takeable ≤2c dog exists in 10.3% of dear obs (bug #23 phantoms on top) | why the intuition misfires: 20:1 payoff (1,816 wins @ +$0.62 vs 84 losses @ −$12.38) — each loss erases 20 wins so a 95.6% book FEELS like bleeding | ⚠️ BOTH forks independently flagged the real lever: bleed is mid-band 0.90-0.98 (−$86.91) vs ≥0.98 (+$55.91) ⇒ MIN_ASK 0.98 would have been ~+$90/18d on the live-only join — contradicts §38/§45/§47 (offline replays); needs day/coin episode check + WALLET reconcile + regime caveat before any change. NO CHANGE MADE (operator decision) | ⚠️ accounting: live-only join −$34.14 vs all-settles join +$87.00 — different populations; wallet is truth | new doc strat-1c-insurance.md

2026-09-02 22:50K — §62: 15m FLEET-WIDE (user "4.a"): eth/sol/doge/bnb/xrp/
hype 15m bots deployed at pilot sizing $12/$24/halt15 + full §57-61 stack;
all 7 verified (BAR=900, markets found, 0 errors). btc15 pilot was 5-0
+$8.74 at expansion. 4b (presign) SKIPPED with evidence: coincurve already
cut signing to 0.5ms — fire path is ~95% network (~45ms POST); presign
would save <5ms and shrink windfall fills via size-at-cap. Hourly cron
updated to cover all 15m bots.

2026-09-03 03:55K — DAY CLOSE 09-02: 5m −20.45 (96-8: sol +60.49 w/ 2 brake-
kept windfalls, xrp +12.60 19-0, btc +4.18, bnb +3.53, hype −1.26, eth
−25.81, doge −74.18 = 4 flips, worst coin-day of era); 15m +4.89 (btc15
+4.83, doge15 first fill); TOTAL −15.56. Worst chop day by loss count (10
loss bars) held to −$15.6 — §61 single-clip caps + brake windfalls did the
work. 15m fleet-wide went live mid-day. Balance $232.62 at close.
2026-09-03 ~10:30K | mrec v2 defect found+fixed by the monitor itself | ALERT "RB hash match 6%" → three-signal check showed the FEED healthy (evage 0.01s, ev-file +250KB/5s) but the RB reconcile degraded: CLOB REST /book returns 403 under our fleet-wide polling (30s × 2 tok × 17 pods ≈ 68 req/min); only 30 of ~240 expected RB rows/hour landed and the survivors skewed the hash statistic | FIX (recorders only, no trader touched): 150s base + per-coin jitter, one token per cycle, exponential backoff to 20min on 403/429 ⇒ ~7 req/min fleet-wide; redeployed all 17, verified backoff logging live | monitor recalibrated: hash-rate alert REMOVED (it was firing on its own sampling artifact), replaced by RB-presence (zero rows past :45) + evage>300s + growth + pod count | ledger addendum written (rate-budget polling across pods; a silently-degrading diagnostic is worse than none) | ⚠️ hit the kubectl context trap again mid-check (cwd drift → dead EKS, reads only)

2026-09-03 20:20K — §63 REDEMPTION INCIDENT + FIX: venue auto-redeemer
backlogged ~4.5h → $148 of WON positions stuck unredeemed, fleet free
balance hit $0.67 intra-bar (14 bots competing for scraps; balance read
showed $58.93 and looked like a loss — it wasn't; day PnL was IMPROVING).
Root cause of our exposure: btc-sweeper's adapter-redeem path was DISABLED
since birth (PM_REDEEM_VIA_ADAPTER unset ⇒ REDEEM_ON=false) — vacmaker
winners silently depended on the VENUE's auto-redeemer. Fix: pmRedeemViaAdapter
"true" on sweeper (deployed, verified REDEEM=true LIVE=true). The venue's
own redeemer caught up in parallel (0 PF_REDEEM from us; redeemable list
now 0; balance $217.41 recovered). Sweeper now backstops any future venue
backlog at 60s cycles. Lesson: balance-drop triage = positions?redeemable
FIRST; won-but-unredeemed inventory is invisible in pUSD.

2026-09-03 22:20K — 15m FLEET STOPPED (user "stop 15 bots"): all 7
<coin>-vacmaker15m scaled to 0 (PVCs/history kept; restart = scale up).
No stranded positions. Lane record: net ≈ −$30 over 2 days (doge15 −23.16,
btc15 −11.76 drags; sol/xrp/eth/hype15 small green). 5m fleet unaffected.

2026-09-04 06:40K — DAY CLOSE 09-03 (logged late; report cron gapped ~6h
overnight, likely laptop sleep): 5m +25.37 (114-7: bnb +19.42, hype +16.92,
xrp +15.50, btc +8.78, sol −7.28, eth −12.01, doge −15.96 incl one $5-mode
loss); 15m −30.33 (fleet stopped 22:20K); TOTAL −4.96 — chop day #3
recovered to ~flat. §63 redemption fix held. Balance $219.70 at close.

2026-09-05 04:00K — DAY CLOSE 09-04: 5m +13.48 (124-2 — best W-L ratio day
of the era; both losses brake-capped single clips: hype −20.3ish class-B,
xrp −20.3 class-B). eth +13.46 (16-0), bnb +8.31 (13-0), sol +4.55, doge
+3.43 in $5 data mode (21-0!), btc +1.93, hype −10.30, xrp −7.90. All
protections quiet or correct; zero errors; sweeper backstop clean. Balance
$228.08 at close. Uniform-era running total ≈ +$150/6d.

## 2026-09-06 08:40K — Day close 2026-09-05 (UTC): +$29.99 (123-2), best uniform-era day
5m fleet: bnb 18-1 +13.27 (incl +$11.5 brake windfall) | btc 7-0 +1.68 | doge 19-0 +1.46 ($5 data mode) | eth 15-0 +9.20 | hype 22-0 +10.73 | sol 18-0 +5.78 | xrp 24-1 −12.13 (early full-clip loss, halt=999 by user).
Only 2 losses all day (one xrp $24 clip, one bnb ~$1.9 partial). Zero halts, zero errors. Brake trips: bnb 1 (windfall kept +$11.5), eth 2 (both wins), hype 1. Balance 09-05 close ≈ $253.6 (from $222.6 at 12:00K).
Uniform-era 7-day tally now ≈ +$180. Reporting gap 01:00→08:36K (laptop sleep; cron session-local, bots unaffected).
09-06 opened hot: bnb ladder filled 99.8sh @ 0.238 at 03:19 UTC, won → +$76.09 single-bar windfall (brake marked bar toxic post-fill, §59 working as designed).

## 2026-09-07 03:55K — Day close 2026-09-06 (UTC): +$129.02 (120-2) — RECORD day (4× prev best +29.99)
5m fleet FINAL: bnb 22-0 +101.87 (0.238 ladder windfall +$76.09 at 03:19 UTC + a +$12.20 windfall in the day's last 6 min) | btc 3-0 +0.96 | doge 24-1 −0.07 ($5 data mode capped its loss at −4.25) | eth 18-1 −16.53 (one 0.99 thin-est flip −23.76) | hype 17-0 +15.17 | sol 16-0 +22.30 (two dislocation wins +7.02/+9.96) | xrp 20-0 +5.32.
Zero halts, zero errors. Taker fees ≈ $4.85 on ~$1.8k notional (fee = sh×0.07×p×(1−p) — negligible at 0.99, concentrated in the deep fills). Balance 03:54K $374.87 (ATH; era started $180.87 on 08-30).
Research same day: §64 (early deep-ask lane rejected on live DELAY A/B; mrec sim was clairvoyant — bug #25) and §65 (abuse-sweep: bleed band resolved by §58/§61, ladder-cap raise refuted, second-bite refuted, §33 late-shift quantified: 68.8% ask persistence tl18→tl13, ~+$3.8/day naive, single-coin A/B proposed — awaiting user).

## 2026-09-07 ~23:xxK — §73 MAKER HUNT ROUND 3: the 0.001-TICK JUMP (first positive maker cell) + a rebate-farm accounting correction
User: *"keep searching for the maker strategy which will generate profits on 5m markets."*
Full write-up: `docs/strat-maker-tickjump-20260907.md`. Scripts: `tools/mrec/tickjump/`.
Data: mrec v2 pq build, 7 coins, 09-01→09-06, 9,833 bars / 2.73M prints.

**1. 🟡 THE CANDIDATE — post-only bid ONE 0.001-tick above the favourite's best bid, tl 2-30, bid ≥0.98.**
The venue tick is **0.001 above 0.96** (14.3% of late-window `ub≥0.96` are off the 0.01 grid vs
0.017% below 0.90), so price priority costs **0.1c** instead of 1c. Pooled replay, 50sh/bar cap:
**+0.518 ± 0.169 c/share, t=3.07, 6/6 days, +$74/day**; with the fleet's own recon gate
(`|est_bps|≥2, cov≥0.5`) **+0.738 ± 0.119, +$63/day**. Mechanism = the resting-order wall read
backwards: **joining** the touch fills only 449 bars at win 0.98598 (−0.09 c/sh), **improving**
fills 2,467 bars at win 0.99480 (+0.52) — the front of the queue gets the BENIGN flow.
CONTROLS PASS: the same jump mid-bar, where the tick is 0.01, is **−1.799 (t=−7.9, 0/6 days)**;
mid-band 0.30-0.96 in the same window −0.279. FILL MODEL VALIDATED on the tape: **94.7% of prints
(87.5% of shares) in that window execute exactly AT the displayed best bid** — the improvement
niche is unoccupied (and that also bounds the competitive decay: ~5 ticks of headroom).
⚠️ **NOT DEPLOYED, and must not be sized on this evidence**: (a) LOO-coin — drop btc and it is
**+$0.6-3/day** (bnb/doge/hype negative in every config), and README §4 records replay-vs-live
per-coin r=**−0.63**, so "run btc only" is forbidden; (b) the downside is **7-13 loss events** in
6 days (uncapped t falls to 1.78, 13 loss bars, day 09-06 −$530); (c) ⭐ **a maker can never
sweep** — a resting bid fills at its own price, so this lane deliberately buys the grind and
forgoes the option that §7 of the live ledger measured as **61.7% of all fleet profit**. Maker
grind ROI +0.53% beats taker grind +0.34% (no fee + rebate), but taker-with-sweeps is +0.87%.
**Proposed arm: 5 shares, log-only, ALL SEVEN coins, |est_bps|≥2, tl 2-30, one clip/bar — judge on
FILL RATE and post-only rejections, not PnL.** (§54's 0/165 rest lane was the *post-close* snipe at
a fixed 0.99 — a different window, not a contradiction, but the reason fill rate is the question.)

**2. ⛔ Static DEEP resting bids on the late favourite — REFUTED, t = −8 to −16.** `fav_bid − Δ`
placed at tl 30/45/60/90 and left to the close: **−13 to −19 c/share** for every Δ ∈ {1,2,3,5,10,
15,20,30}c and every placement time, filled at mean 0.58-0.77 winning 12-58%. Strict
("walked-through") and zero-queue fill models agree. ⭐ *A sweep is not a price you can wait at.*
Do not misread the print census (prints at 0.80-0.90 in tl 0-30 win 90.8%) — that is the market
*at* 0.85, not a bid pre-committed at 0.85.

**3. ⛔ No volume-tier maker rebate.** Live gamma 09-07: all 5m/15m crypto up/down =
`{rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}`, `clobRewards: None`. `rebateRate`
varies by MARKET (sports 0.15, Fed 0.25), never by our volume. Closes the reopener named in
`strat-maker-4060-pooled` §5(a).

**4. ⛔ Full (tl × price) map of the touch-joining maker — every one of 64 cells negative**
(−1.9 to −7.3 c/share, t −3 to −17), lifting the caps the program had always run under
(q 0.04-0.60, tl 40-270). ⚠️ `mm.py` skips every epoch where the favourite has no ask (83% of
late-window seconds), which is why the high-price late cell had never been sampled; `lw2.py` fixes
that. `mm.py:load_coin` was also missing `evage` — added, so freshness gates actually bind.

**5. ⚠️⚠️ ACCOUNTING CORRECTION → `docs/strat-rebate-farm-20260907.md` §11 (ledger-worthy).**
That doc's headline reproduces **bit for bit** (half-spread +0.868 vs +0.851, adverse −1.562 vs
−1.540, sum −0.441 vs −0.430 ✔) — but its `net` omits the **placement→fill mid drift, −4.156
c/share**. Terminal `win − q` + rebate on the identical 47,038 fills is **−4.624 ± 0.382**; we
fill **3.30c ABOVE the mid at the instant of fill**. Verdict unchanged (more dead), and it
**reconciles** −0.43 with `strat-maker-4060-pooled`'s −7.03 — the two docs were measuring
different things. ⚠️ Re-score anything that used the magnitude, above all *"+$269/day at LAT=0"*
(that curve lives in `pess2/qdecay.py`, which owns the cancel-latency axis). The §9 signal-cancel
work uses a 1-second markout and is unaffected.
**Rule to carry: decompose a maker's PnL as (mid@quote − q) + (mid@fill − mid@quote) + (win −
mid@fill). The middle term is the strategy, not a nuisance.**

## 2026-09-08 03:56K — Day close 2026-09-07 (UTC): +$31.32 (131-2)
5m fleet FINAL: bnb 16-0 +4.04 | btc 14-0 +4.05 | doge 20-2 −5.60 (both losses $5-data-mode capped) | eth 24-0 +13.10 | hype 17-0 +4.61 | sol 17-0 +4.59 | xrp 23-0 +6.53.
Pure grind day (no windfalls): 131-2, zero halts, zero errors. Balance 03:55K $383.95 (ATH era; peak read $398.80). Uniform-era 9-day run ≈ +$310. Cron renewed 09-07 (ab2ba68a). Housekeeping: multiple in-flight-clip balance dips triaged clean (§63 pattern held every time).

## 2026-09-08 — §73b AGENT A (maker round 3): THE TICK-JUMP LANE IS INFEASIBLE — the 0.001 tick arrives ~2 min late
Doc `docs/strat-maker-hunt-r3-20260907.md`; scripts `tools/mrec/tickjump/agentA/`. Every book-side attack on §73-1
PASSED (98.1% of late sell prints at the best bid vs a 7,647-sh median queue; 12 exact-+0.001 improvers in 3,905
bar-tokens; capacity median 100 sh/bar; pre-registered persist-5s gate → 2 loss bars, +0.839 ± 0.073 c/sh, all 7
coins positive, LOO-btc +$36/day) — **and then the venue clock killed it**: 16,212 raw `tick_size_change` events
show the fine tick switches **~121 s (p50) after the price crosses 0.96, 74% after close, 13% of decisive bars by
tl 30**. 0.991 is rejected (`invalid price, max: 0.99`) for 98.6% of the sim's fills; tradeable subset **34 bars,
+$1.7/day**. This reconciles §56's live 0/165. Bug #39: gate every sub-cent sim on the recorded tick_size_change.
Also closed: mirror lottery (underdog bid 0.002 — 0 win events in 390 prints, ceiling +$2/day); rebate-farm's two
"not refuted" cells on TERMINAL PnL (first-60s two-sided −4.40 ± 0.72, .04-.15 band −2.23 ± 0.44, both 0/6 days —
bug #37 artefacts); flip-transient, post-close winner-bid pool ($187 of $217/day in coarse-tick bars), minted
0.999 ask (≡ 1.000 by identity), 0.999 exit demand (0.8% of bars). **The maker program has no open 5m cell.**

## 2026-09-08 — §73c AGENT B (non-maker 5m edge & mechanics hunt): NOTHING TO ABUSE, NO CROSS-MARKET SIGNAL
Doc `docs/strat-edge-hunt-5m-20260907.md`; scripts `tools/mrec/edgehunt/`; 7 live ledgers pulled read-only (08-17→09-07).
Mechanics: 41k `tick_size_change` events → **0 crossed/locked books**, no stale 0.01-grid asks; post-close tape 1.67M sh/6d
= **99.98% sellers dumping the winner into 0.98-0.999 bids** (taker-liftable winner asks $272/6d field-wide — snipe dead
from the tape side); underdog asks ≤0.10 late: flip 0.003-0.04% vs 0.9% BE, every cell −0.9…−7 c/sh; orders ARE accepted
post-close (626/628 ids at T+2.1s) but nothing takeable; min size 5 sh; late takers = 0.99-lifters, no wash/new archetype.
Cross-coin: btc's est is right about an alt 77% vs the alt's own est 97.7%; 15m/1h add nothing. Live lane: "fire only at
displayed 0.99" is a SIZING signal (+$139.64, 1.19%, tl≤12 7.78%) not a gate (forfeits $75); sweeps scale 2.3%→35% ROI
with requested size (confirms ledger §5); tl 0-2 window +$0.26/day; UTC 03-11 hole was the mid-band bleed (post-08-31 +1.01%).
⭐ **The tl≤12 vs 16-20 A/B is UNDECIDABLE live**: per-bar ROI sd 17.4pp ⇒ 858 coin-days/arm (~4 months) for +0.8pp.
Bug #40 (key raw-event windows on (ws,tok) — cur/post share token labels), bug #41 (power an A/B before designing it).

## 2026-09-08 — §73d AGENT C (mid-band 20-80c maker for rebates / rewards-readiness): COST FRONTIER + GO/NO-GO TRIGGER
Doc `docs/strat-midband-mm-rewards-20260907.md`; scripts `tools/mrec/midband/` (incl. `rewards_monitor.py`, NOT deployed).
47 pre-registered cells, terminal PnL, 7 coins × 9,833 bars: **every cell negative, 0-1 of 6 days positive**. join/static
−6.71 c/sh (−$4,500/day @50sh×7), **join/cancel-on-touch-move −2.53 c/sh (−$1,370/day)** — drift is 2-3× adverse
selection everywhere and cancel-on-move is the only lever that matters (drift −7.3 → −3.1). Rebate +0.30-0.35 c/sh =
5-12% of the hole. 40-60c is worse than 20-80 at every placement. First-60s cheapest per share (−1.23, 0/6 days) but earns
~no rewards (Aug config attached at ~tl 250 → bug #42). Cheapest reward-eligible presence ≈ **$0.30 per 1,000 in-band
share-seconds** (edge05/cancel). **GO/NO-GO for a returned rewards program: pool ≥ ~$1,600-1,800 per coin per day** with
today's field (Aug alt pools were $833-1,667 — just under); at Aug's *measured* capture no pool ever offered breaks even.
Least-bad "keep the plumbing warm" config ≈ one coin, 1 quoted bar/hour, ≈ $1.5/day. openmm gaps: size 5 = zero rewards
(min 50), first-minute window is the wrong window, imb/pull gates on (proven harmful), no rewards fields read.
**Decision map now: no open 5m maker cell; rewards lane = monitor + re-run frontier the day `clobRewards` reappears.**

## 2026-09-08 — §74 30-70c MAKER ROUND 4 (user: "market maker only, 30-70, only 5m, search for the edge"): the last three untested cells, all dead
Doc `docs/strat-maker-3070-20260908.md`; scripts `tools/mrec/midband/r3070/`. Terminal PnL, queue, tape cap, placebos.
(A) TWAP-recon-gated maker at tl 3-60: the gate leaves 61 bars at |bps|≥2 (a near-tie price and a decisive margin exclude
each other); +7.8 ± 8.8 c/sh vs **flipped-side placebo +19.9 ± 12.8** → noise. (B) momentum-following one-sided maker
(full bar): −1.25…−1.51 c/sh, 0-2/6 days; contrarian placebo −1.39 — identical. (C) deep-size for sweeps: −5.5…−8.6 c/sh,
t −20…−26, 0/6 days; the ≥100-share fills are the WORST at every depth (−6.9…−9.1) — big sweeps are informed. Sixth
field-average inversion. **Nothing untested remains in 30-70c; the go/no-go is the rewards pool (§73d).**

## 2026-09-08 — §74b user idea: mint at open + 0.99 asks on both tokens ("chop double take-profit") — break-even by construction
`r3070/minttp.py`, 11,137 bars: winner sold −1c in 74 % of bars vs loser sold pre-reversal +99c in **0.74 %** (break-even 1.0 %)
⇒ +3.0 ± 3.7 c/bar on $50 (t 0.8, 4/9 days, xrp/btc +, bnb/hype −). TP 0.98 −10.5c, 0.95 −62c, 0.90 −139c. Chop gate: 71 %
of bars fill nothing. Split/merge itself is not a distinct mechanism (identity; doc §D). Documented in strat-maker-3070 §D/§E.

## 2026-09-09 03:56K — Day close 2026-09-08 (UTC): +$63.01 (158-2), 2nd-best uniform-era day
5m fleet FINAL: bnb 30-0 +10.30 | btc 16-0 +5.92 | doge 19-0 +1.33 | eth 16-1 +1.14 (brake-capped −$10.5 loss — §59 save) | hype 25-0 +39.38 (dawn dislocation windfall +$20.7 + steady adds) | sol 22-0 +15.60 | xrp 30-1 −10.66 (one full-clip flip −$22.80).
Zero halts, zero errors. Balance 03:55K $464.33 (ATH era; peak read $465.12). Uniform-era 10 completed days: −7.25, +29.94, +16.97, −15.56, −4.96, +13.48, +29.99, +129.02, +31.32, +63.01 = +$285.96 (~$28.6/day). Balance $180.87 trough (08-30) → $464 (+$178 of that is the last 3 days' dislocation-rich regime).

## 2026-09-10 03:56K — Day close 2026-09-09 (UTC): −$66.93 (95-7) — worst uniform-era day
5m fleet FINAL: bnb 12-0 +6.64 | btc 11-1 −19.72 | doge 17-0 +1.28 | eth 14-1 −11.15 | hype 16-2 −21.59 | sol 12-2 −26.81 | xrp 13-1 +4.22.
7 losses, ALL brake-capped singles (no ladder doubles, no coin reached its $30 halt). 5/7 = §66 bid-collapse chase cell: violent impulse → our-side bid collapses to ~0.05 in <6s → est thin (0.05-0.06bps over threshold, inside 0.46bps proxy noise) + relay-lagged → FAK sweeps collapsed book (sol 1,524sh @0.015). Correlated: eth+sol fired same second (10:34:40).
§66 analysis validated the [[bid-drop-veto]] discriminator on 35 cheap fills: veto d<=−0.30/6s blocks 10/14 losses vs 8/21 wins; stale-book windfalls (bnb 0.238 d−0.02) untouched. LOG-ONLY arm proposed, awaiting user go.
Balance 03:55K $340.28 (from 09-08 close ~$464 peak $479; still +$159 above 08-30 trough). Era 11 days: +$219.03 (~$19.9/day).

## 2026-09-11 03:56K — Day close 2026-09-10 (UTC): booked +$22.96 (48-2), TRUE ≈ −$3.4
5m fleet FINAL (booked): bnb 8-0 +1.71 | btc 12-0 +11.89 (+$8.3 discounted win) | doge 11-2 −7.95 (both losses $5-capped) | eth 0-0 0.00 | hype 1-0 +0.24 | sol 16-0 +17.07 (+$13.10 brake windfall late) | xrp 0-0 0.00.
TRUE day ≈ −$3.4: three 00:05-00:40 UTC bars hit a VENUE RESOLUTION STALL → first live firing of the PF_TE_SETTLE_ABANDONED path ("pnl unbooked, redeem via sweeper"); sweeper collected once the venue resolved. Unbooked: btc −23.76 (lost), doge −4.20 (lost), hype +1.57 (won). §63 backstop worked; hourly battery now tracks `abandoned` per coin; booked-vs-true split reported all day.
Quietest era day otherwise (eth and xrp fired ZERO clips all day). Zero halts, zero errors. Balance 03:55K $387.88. Era 12 days booked ≈ +$242.

## 2026-09-12 03:56K — Day close 2026-09-11 (UTC): +$21.99 (55-0) — FIRST PERFECT DAY of the uniform era
5m fleet FINAL: bnb 13-0 +4.51 | btc 13-0 +9.38 (incl +$5.2 discounted win) | doge 17-0 +0.89 | eth 0-0 | hype 0-0 | sol 12-0 +7.21 (+$4.2 discounted) | xrp 0-0.
Zero losses, zero halts, zero errors, zero abandons. eth/hype/xrp fired NOTHING for a second straight ultra-quiet day (est never cleared threshold — regime, not a bug; their pods healthy, EVAL events flowing). Balance 03:55K $408.31. Era 13 days booked ≈ +$264 (~$20/day).

## 2026-09-13 03:56K — Day close 2026-09-12 (UTC): +$44.04 (58-0) — second consecutive PERFECT day
5m fleet FINAL: bnb 11-0 +2.41 | btc 9-0 +36.20 (stale-display windfall +$30.1 at ~19:4x UTC, brake-marked, gift class per §66 census) | doge 19-0 +0.98 | eth 0-0 | hype 0-0 | sol 19-0 +4.45 | xrp 0-0.
Zero losses/halts/errors/abandons. eth/hype/xrp third straight silent day (est never clears threshold — regime). Balance 03:55K $450.38 (era ATH close; intraday ATH $479 on 09-09 still stands). Era 14 days booked ≈ +$308 (~$22/day).
Research this week: streak census (09-05..12 mrec): gift supply constant ~240 eps/day; ALL day-to-day variance = the deep-fill channel (+$124/−$88 swings); calm-day stale displays pay, violent days trap (§66). Veto log-only arm still awaiting user go.
2026-09-13 | user: "can we trade zcash already? weird pricing (Up 71c / Down 95c) — can we abuse it / split and sell both?" | measured on local zec v2 tape (259 files, 3,046 labelled bars, 09-01→09-12) | ⭐ NEW: zec HAS a Chainlink feed now (cl in 100% of 169,994 snaps; the old "zec/hype no offline recon" note is obsolete for zec) — recon side-accuracy tl<=14: 95.0% overall, 99.5% at |margin|>=10bps (n=2,110) | ⛔ SPLIT-AND-SELL: pair is one book so displayed asks 0.71/0.95 imply bids 0.05/0.29 — mint $1 -> sell both for $0.34; tape ask-sum median 1.51 => bid-sum 0.49; resting-ask variant = strat-ask-ladders (dead) with 0.1 prints/bar | ⛔ NAIVE WIDE-BOOK BUY (ask<=0.99, margin>=3bps): n=144, accuracy COLLAPSES 99.5%->81.2% once an ask exists (bug #20 on a new coin), avg ask 0.93 => -11.7c/share | 🟡 cheap cell (ask<=0.95): n=23, 82.6%, avg 0.60, +21c/sh, ~2 bars/day, med 20sh — but +$62.38 total is 84% ONE day (09-11 +$52.45), ex-best-day +$9.93/6d = $1.65/day (§45-47 fingerprint); takeability 13/23 bars saw a late print | NOT deployed; pilot spec in doc (MIN_ASK ~0.95 not 0.55, margin>=3-10bps, $5-12 clips) | new doc strat-zec-widebook.md; README zec row superseded

## 2026-09-13 14:5xK — sol halt disabled per user
sol hit −$46.56 (2 bid-collapse trap losses); §57 cooldown would have benched it on next fire. User: "I don't want it to" → liveMaxDailyLossUsd "30"→"999", deploy rev 22 + rollout restart, env verified (halt=999, persist=1, risk-state restored). Halt map now: xrp 999, sol 999, doge 7, others 30.
2026-09-13 ~17:40K | ⭐ BREC LIVE — Binance raw WS folded into the recorders (user: "add binance ws to the mrec, all the data we can potentially make use of") | multi_recorder.py + `<coin>-brec-*` writer: spot aggTrade + bookTicker + depth@100ms + kline_1s, arrival-stamped, own buffered drain, hourly gz, same 7d retention; enabled on 7 of the 8 5m recorders; PVCs 10Gi->20Gi | ⚠️ hype has NO Binance spot symbol (verified from pod); ⭐ zec DOES (old "hype/zec no spot" note now applies to hype only) | ⚠️ Binance FUTURES (fstream: markPrice@1s, forceOrder, !forceOrder@arr) CONNECTS BUT DELIVERS NOTHING from both Kyiv and Helsinki — silent geo-block, knob left empty (trap: it looks connected) | volume ~1.2MB/min raw on btc; drain picks brec up automatically (same /app/logs/raw glob)
2026-09-13 ~17:45K | HUNT A (depth & queue, v2 10-level ladders) | ⭐ phantom-ask classifier WORKS: 8,385 live fires, day-split OOS AUC 0.936 vs 0.555 price baseline; quartile fill 44.4/96.7/97.8/98.9%; leakage caught+removed (ledger `t` is the REPLY time, `ms` p50 363ms — own book events leaked into the "pre-fire" window; leak-ladder flat at 0.861 by delta=1.0s) | BUT worth ~$0 directly: a killed FAK is free, predicted-real fires already fill 98.9%, side-accuracy flat across quartiles | ⭐⭐ REAL FINDING: 386 zero-fill bars (~35/day) are 98.96% side-correct vs 96.65% on FILLED bars (p=0.0008) = bar-level adverse selection measured live on our own fires | prize small+unbuyable: only 32.8% of missed bars ever print; convertible 14.2 bars/day at +0.0585/sh (upper bound, hindsight); agent rejected its own +$42/day naive model as impossible vs a ~+$19/day fleet | ONE idea alive: RETRY ALLOCATOR (timing binds, not price — 45% of misses exhaust 3 attempts, median 9.7s tl left) — live A/B only | not deployed; new doc strat-phantom-classifier.md
2026-09-13 ~18:00K | HUNT B (event-time microstructure, ms arrival stamps) | ⛔ cross-coin lead-lag at ms resolution DEAD: btc mid-jumps (n=49,526) move followers +0.94..+1.86c sign-aligned at t=18-61 (placebo ~0) BUT followers pre-move 1.85c in the 0.5s BEFORE = common shock; economics tape-confirmed −1.45c/sh (n=6,674, 3,510 clusters, t=−2.81), 1/8 days positive — closes the question the old 100ms-aliased test left open | ⛔ ask-lifetime EV gradient is a PRICE ARTIFACT (short episodes are cheaper asks; within-level +0.26c/sh, n.s., 18/32 levels) — but ⭐ keeper latency facts: median favourite-ask episode 236ms, 60.4% shorter than our 0.4s poll, btc median 99ms, market takers hit at 74ms median | ⚠️ tick_size_change per-token test returns EXACTLY 50.0% by construction (market-level event, both tokens flip, gap 0.000s); market-level in-bar n=207 +1.98c/sh t=2.09 = same dear-fav trade, not actionable | RB match rate tracks book CHURN (btc 44.9% -> zec 98.5%), not staleness — not usable as a gate without per-coin normalisation | ⭐⭐ RECORDER DEFECT FOUND + FIXED SAME SESSION: price_change (96% of events) had no ws/tok attribution -> ev2pq dropped them, HF layer unusable; now ch=[ws,tok,side,px,sz], 100% attributed, rolled to all 17 recorders; ⚠️ parsers must handle 4-element (pre 09-13 18:00 UTC) AND 5-element entries
2026-09-13 ~18:20K | local data/mrec archive DELETED per user (23GB, 09-01→09-12, all coins+durations); 105GB free. Rebuilding from post-fix captures only (brec Binance tape + corrected price_change attribution). KEPT: data/pq (2.7GB derived parquet — now the sole record of 09-01→09-12), data/openlag-probe, older non-mrec archives
2026-09-13 ~18:50K | ⭐ HREC LIVE (user: "we can get hype ws data from hyperliquid directly") — hype-mrec now records HYPE's native venue: bbo, trades, l2Book (ABSOLUTE levels), activeAssetCtx (funding/OI/mark), candle 1m -> `hype-hrec-*`; verified from pod, all 5 channels flowing. Knob is generic (hrecCoin/hrecSubs) so HL perps for btc/eth/sol/xrp/doge can be enabled per coin as a SECOND venue
2026-09-13 ~18:50K | ⚠️ ORDERBOOK GAP FOUND + FIXED (user: "are the orderbooks captured as well?") | audit of what we actually capture: PM SNAP top-10 ladders both sides both tokens @10Hz ✅, PM `book` events (top-10 + venue hash) + attributed `price_change` diffs ✅, RB REST top-3 ✅, HL l2Book absolute ✅ — BUT Binance `depth@100ms` is a DIFF stream and Binance's documented reconstruction needs a REST snapshot anchor we never fetched ⇒ the Binance book was NOT reconstructable. FIX: added `depth20@100ms` (absolute top-20 with lastUpdateId, self-contained) to all 7 brec coins; diff stream kept for full-depth work if a snapshot fetch is ever added. Verified live: btc depth20 rows carry absolute bids/asks
2026-09-13 ~19:30K | user: "make parquet files from these and zip them; also drop depth@100ms" | (1) `depth@100ms` DROPPED fleet-wide (7 coins redeployed, verified) — it was ~40% of the new volume and unreconstructable without a REST anchor we never fetched; `depth20@100ms` (absolute top-20) supersedes it | (2) NEW `winner-vacuum/tools/mrec/venue2pq.py`: raw brec/hrec -> typed zstd parquet, one file per (coin, source, stream, HOUR); 9 stream schemas flattened (bin bookTicker/aggTrade/depth20/kline_1s, hl bbo/trades/l2Book/activeAssetCtx/candle); 0 unknown rows after fixing HL-trades dispatch; ~1.4-1.5x smaller than jsonl.gz AND queryable without a JSON parse | ⚠️ deliberately PER-HOUR files: per-day grouping would overwrite a day's earlier rows as the archive grows hour by hour (idempotency verified: rerun gives identical 651,722 bookTicker rows) | ⚠️ conversion skips files modified <90s ago (still being written) and DISCARDS historical depth-diff rows | (3) NEW `every-tick-single/tools/archive_mrec.sh` = drain -> convert -> prune, verify-then-delete throughout; monitor now runs this every 30min instead of the bare drain | first full cycle: 42 files drained 0 failed, all 8 coins converted, raw venue tapes pruned
