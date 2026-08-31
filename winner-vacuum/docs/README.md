# winner-vacuum docs — ORIENTATION HUB (read this first, then decide)

**RULE: update these docs in the same session as any experiment. Max detail,
dated. One strategy per file. Verify capabilities against the repo before
declaring them missing.** (user directive 2026-08-13)

## 1. DECISION MAP — "I'm considering X" → verdict in one line

| If considering… | Verdict | Why (one line) | File |
|---|---|---|---|
| **ANY maker / market-making idea on PM crypto updown** | ⛔ **PROGRAM CLOSED 08-21 — read this FIRST** | a resting bid quoted 1.5c BELOW mid FILLS 0.47c ABOVE it (48% of fills above the prevailing mid) vs a +0.35c rebate ⇒ −0.47c adverse selection per fill, before any strategy logic. Duration-independent. 5m/15m/1h all measured negative; every mitigation (exits, taker completion, volume, mint/merge, vol gates) refuted with RAND==real | [maker-program-2026-08](maker-program-2026-08.md) |
| Resting BIDS on 5m (pairs, rewards, any exec) | ⛔ DEAD (re-confirmed 08-17 WITH the $1M rewards counted) | in-band 50sh two-sided: singles −$1,300/d vs rewards+rebates+pairs ≈ +$700/d, all 7 coins; velocity/level gates CANNOT dodge the toxic fill (43/48 loser-singles fill at flat lead-velocity) | [strat-rewfarm](strat-rewfarm.md) |
| 15m in-band reward-farm | ⛔ negative (08-17) | btc −$205/d, eth −$130/d at 50sh; 3-4× better than 5m but the wall stands | [strat-rewfarm](strat-rewfarm.md) |
| **4h reward-farm (rewfarm)** | 🟡 PILOT — paper btc+xrp since 08-17 23:33 | 4h in-band field ~EMPTY → 50sh two-sided ≈ 50-77% of alt pools ($333/d) & 5-15% of btc ($1,667/d); oscillation completes pairs (1h mechanism); AUG-ONLY program | [strat-rewfarm](strat-rewfarm.md) |
| **Mean-reversion bot: buy the losing side for the occasional reversion** | ⛔ CLOSED 08-23, §42 — the biggest test ever run here (376k obs, 28.4k bars, 19d, 7 coins, NO estimator) | the dog is over-priced at EVERY price and EVERY moment: −15.7% of stake pooled (n=119,408; true win 15.14% vs a 0.1795 ask), every coin negative, 18/19 days negative; conditioning on the crush or on a violent move makes it WORSE (the intra-bar path is momentum); scalping the retrace −13…−22%; the best cell anywhere is −3.8%. Fair 0.1514 vs ask 0.1795 vs bid 0.1486 ⇒ even a PERFECT maker fill earns +1.8% gross, erased by the −0.47c resting wall | [strat-reversion](strat-reversion.md) |
| **"Buy the dip" / the opposite of vacmaker (buy the cheap side, hold to redemption)** | ⛔ nothing to deploy (08-23, §41) | the lane is ALREADY live (`MIN_ASK=0.55`) and IS the profit centre (ask 0.75-0.90 = +3.98% ROI, +$34.54 of the fleet's +$50.85); going below 0.55 is unreachable — a displayed ask <=0.75 fills **11%** of the time and the fills are the WRONG ones (71% side-correct vs **100%** on the bars we hammered 11x and never filled); selling instead of redeeming gives up 24.9c/sh | [strat-dipbuy](strat-dipbuy.md) |
| Buying the mid-bar "favorite" on dips (maker) | ⛔ refuted 08-17 | 507 fills, 63% win, −6.2¢/sh — \|lead\|≥1bps is already priced into the mid | [strat-rewfarm](strat-rewfarm.md) §2 |
| 15m batch pairs | ⛔ stopped | live mix pair +$2.50 vs residual −$5.51; completion too low | [strat-poolfarm-15m](strat-poolfarm-15m.md) |
| 1h pairs (batched) | ⛔ **HALTED 08-21 after ~28h** — sim CALIBRATED to live (−0.246 vs −0.238/bar); resting orders fill 0.47c ABOVE mid (48% above), i.e. −0.47c adverse selection vs a +0.35c rebate; ceiling ON ⇒ good pairs+ruinous residual, OFF ⇒ no residual+below-par pairs, mutually exclusive; exits/taker-completion/volume all refuted (RAND==real ⇒ pure cost). Cost of finding: −$7.2 | ~~RELAUNCHED LIVE 08-20~~ — 8/8 bars paired, unpaired 20% vs 53% at 5m, +$10.70; venue-truth reconcile added to poolfarm (3 bugs in it, see doc) | see RELAUNCH section | [strat-poolfarm-1h](strat-poolfarm-1h.md) |
| 1h pairs (original) | ✅ works, STOPPED by user 08-14 23:21 | 7/7 prior pairs +$1/bar; relaunch bar1 = designed worst case (−$5.10 residual) → user stopped; 1h DOES pay maker rebate (rebateRate=0.2, corrected 08-14) — economics ~$15-25/day if ever restarted | [strat-poolfarm-1h](strat-poolfarm-1h.md) |
| Anything PRE-OPEN (bids or mint-asks) | ⛔ DEAD | pre-open buyers are INFORMED (prior-bar drift); both directions measured −$121…−$705/day | [strat-preopen](strat-preopen.md) |
| Mint + flat ask ladders in-bar | ⛔ DEAD | −$880…−$2,618/day optimistic (but see ⚠️ dataset caveat in file) | [strat-ask-ladders](strat-ask-ladders.md) |
| Mid-relative INVENTORY-SKEWED MM (the pro archetype) | ⛔ DEAD (final, 08-13) | full-bar: 5m −$2,208…−$3,151/day (skew cuts loss 7× vs K=0 −$16k — damage-limiter, not edge); 1h −$70/day | [strat-ask-ladders](strat-ask-ladders.md) |
| Intra-bar flipping (buy 50 sell 51) | ⛔ DEAD | momentum books; more flips = more loss | [strat-mm-flip](strat-mm-flip.md) |
| Speed/co-location/more CPU | ⛔ pointless | maker fills are atomic; 100ms-reaction sim identical to 500ms; PM 403s DE/US anyway | [strat-poolfarm-5m](strat-poolfarm-5m.md) #10 |
| Taker strategies at our size | ⛔ scale-gated | fee 0.07·p(1−p); rebate tiers need $200k-10M/30d weighted vol; incumbents pay half fees | [strat-taker-rebates](strat-taker-rebates.md) |
| Copying leaderboard winners mechanically | ⛔ proven twice | July: two validated winners copied tick-for-tick, both −EV; "edge is selection, not rule" | [strat-ask-ladders](strat-ask-ladders.md) |
| Copying "Sylldra" 0xfd9b7636 (mid-bar 50c buyer, looks stable on the profile page) | ⛔ nothing to copy (08-30) | 5,317 buys / 0 sells, $8.50 clips, 5m btc/eth/sol only; gross +$2,663 but **est. taker fee −$1,085 ⇒ net +$1,568 (+3.46%)**; PM's displayed $2,713 profit is GROSS. Calibration edge ≈ +3pp ≈ the fee. Its 0.40-0.60 volume lane: Apr +2.74% → **Jul +0.01% → Aug −2.21% net**, and it sized up 6× into that. Only durable lane = tl≤45s / px<0.30 (+15-20% net ROI) = our own cheap-tail seam, caps ~$150/mo | [wallet-sylldra-0xfd9b7636](wallet-sylldra-0xfd9b7636.md) |
| Mint→hold winner→salvage loser @1¢ | ⛔ DEAD post-TWAP (stopped 08-14) | 16h live: 0/27 fills. The 1¢ level ≡ 0.99-bid queue now walls up EARLY (median 942sh/p75 4.6k at t−45) — flow never reaches a late 35sh ask; early placement blocked by flips (4.8% @t−90 ≥8bps) | [../MINTSALVAGE.md](../MINTSALVAGE.md) §8 |
| T−4.5s TWAP winner buy | ✅ tiny supply | ≥0.25bps band only, 1-2 bets/day fleet-wide | [../TWAPEDGE.md](../TWAPEDGE.md) |
| 1h/1d late-window taker (Binance-settled) | ⛔ no supply (08-15) | signal PERFECT (flip 0.00% ≥3bps at t≤30s) but books swept: asks≤0.98 in 4-7% of bars, ~$1.2/day capturable 7d-measured | [strat-momtaker](strat-momtaker.md) (same log) |

| Mid-bar momentum-taker (buy rising favorite) | ⛔ DEAD all bands/coins (08-15 pooled n≈6k) | favorite premium > fee saving even under crypto_fees_v2; btc 0.90-0.96 +1.8¢ was n=129 fluke | [strat-momtaker](strat-momtaker.md) |
| **Two-sided MAKER at .44-.56, first 60s (openmm)** | 🟢 LIVE PILOT 08-19 — own program `openmm/`, own account 0xd632c1e1…, btc @ 5sh; 4 live bugs fixed d1 (pair ceiling, failed-cancel reconcile, fill-poll lag, mid-bar-restart cap reset) | plain design dies on latency (signing is only 13ms; the 190ms is VENUE-side, unfixable). **Gating on top-of-book imbalance removes the adverse selection and is latency-INSENSITIVE**: -$65/day ungated -> +$151/day at imb>=0.2 (t=+3.25, 15/19d); field signal monotone over 6 buckets, t=+3.42 on 105k fills. But ~85% of PnL is now directional residual, pair engine gone, sample thin. NOT deployable without a min-size pilot | [strat-openmm-5m](strat-openmm-5m.md) §11 |
| **TWAP-taker (vacmaker)** | ⭐ THE ACTIVE PROGRAM — 6 coins LIVE | reverse-engineered live wallet +$1,358/yr on $95; live fleet 97%+ win at $5 clips; ⚠️ ALL coins settle TWAP-60 | [../VACMAKER.md](../VACMAKER.md) + [vacmaker-offline-notes](vacmaker-offline-notes.md) |
| GTC-rest instead of killed FAK ("catch the vanished ask") | ⛔ REJECTED 08-16 | survivor bias — observed no-fills condition on the signal holding; resters fill exactly on flips (ledger #16); retry-FAK shipped instead | [backtesting](backtesting.md) #16 |
| Mean-reversion on the WEAK-EST cell (buy the 2-5c dog when fav 0.95+ on \|est\| 0.5-1) | ⛔ DEAD (08-18, 2,668 probes) | dog premium 2-4× true flip in every cell (EV −1…−3c/sh); retrace-scalp strictly worse; only fix for the cell = don't trade it (§28 gate) | [notes §29](vacmaker-offline-notes.md) |
| Buying the OPPOSING side at ~1c as a reversal lottery / hedge | ⛔ DEAD (08-17, n=15.7k bars) | 1c loser wins 0.18% vs 1.07% breakeven = **5.3× overpriced**, hi95 0.32% EXCLUDES +EV; −EV in every band/tl/coin; bars do flip (5.6% at T−14) but flip-prone bars are priced 0.10-0.45, never 1c; pair sum median 1.020 so it can't hedge either | [vacmaker-offline-notes §27](vacmaker-offline-notes.md) + `tools/cheaptail.py` |
| Firing the recon gate EARLY (tl 25-30) on a weak est | ⛔ that IS the loss mechanism (08-17, n=28k bars) | flip rate is f(\|est\|, tl): 0.5-1.0bps flips 3.1% live / 10.1% proxy at T−28 but 0.0-0.6% at T−11..14; 72% of our clips sat in that one −EV cell (92.1% acc on buyable bars vs a 0.97 ask); the whale's T−11 median is the whole edge gap; eth needs the STRICTEST gate, not the loosest | [vacmaker-offline-notes §28](vacmaker-offline-notes.md) + `tools/swing.py` |
| **Pre-open signal-informed MAKER ("be the puller")** | ⛔ parked (08-31 census) | the last-10s pre-open maker pool is REAL (+$1.4k/day gross) but btc-only, 5/8 days, back-loaded — it tracks ONE incumbent's skill; aggregate makers −$1,261/day; entrant's marginal quote = the dumb tail (wall unrefuted). Re-open only if census (tools/openlag/premm_*) shows ≥4 coins & ≥75% days positive | [strat-preopen-mm](strat-preopen-mm.md) |
| Funding-timestamp bars / cross-venue 5m arb / delta-hedged vol / consecutive-bar coupling / pre-CPI both-sides | ⛔ all dead (08-31 survey) | noise / no second leg exists / calibration excludes vol mispricing / martingale increments / pair settles to $1 | [strat-preopen-mm](strat-preopen-mm.md) §survey |
| zec vacmaker | ⛔ no venue | market listed but EMPTY: 1.38M snaps/day → 0 trades, book 0.01/0.99; zec-mrec is the tripwire | [strat-poolfarm-5m](strat-poolfarm-5m.md) §zec |
| Taker AFTER bar open on strike displacement (spot vs locked TWAP strike) | ⛔ DEAD (08-29) | book reprices the open displacement within ~2s (ask 0.56-0.60 at δ=2s); win% 2-5pp below ask+fee in every (δ×\|m\|) cell, 27.6k bars | [strat-openlag](strat-openlag.md) |
| Taker in the [ws−3, ws) pre-open window on locked-strike displacement | ⛔ PRICED AWAY (OOS 08-22→29; re-check ~monthly) | the edge was REAL mid-Aug (stale ~0.54 asks, +14c/sh, full battery incl stratified null z=+4.5) but the current pre-open book prices displacement at 0.68-0.76 → |z|≥1.2 = −2..−3c/sh; died between 08-17 and 08-22 (taker-delay 250→50ms change / competition). Signal information persists (nulls z 2-8) — price eats it. Standing re-check: `tools/openlag/` (~10 min). ⚠️ era trap: strike recon must match the era (point <08-07 / TWAP-30 / TWAP-60 ≥08-14) = ledger #24 | [strat-openlag](strat-openlag.md) |
| Post-close flip-harvest taker (buy the cl-true winner the confused crowd dumps) | ⛔ pool too small (08-29 census) | displayed winner-asks ≤0.90 on 2.5% of bars but venue prints bound TOTAL capture at ~$80-170/day for ALL participants (bug-#23 gap ~10×); the real post-close pool is sell-into-bid ≥0.99 ($315/day) = the live snipe-rest pilot's lane. ⭐ keep: T+2 winner detection from relay ticks = 99.98% under ≥40-ticks + ≥1bps guards | [strat-openlag](strat-openlag.md) |

**THE ONE WALL behind every ⛔:** the taker flow (in-bar AND pre-open) is
informed — it lifts the eventual winner. Whoever rests against it loses; no
band, depth, timing, latency, or completion trick has beaten it. Any new
resting-side idea must first explain why it dodges THIS.

**⭐ Everything tried on the vacmaker fleet: one-table index at
[vacmaker-offline-notes §21](vacmaker-offline-notes.md) (18 interventions,
verdicts, loss book, open builds).**

## 2. CURRENT STATE (update on every change!) — as of 2026-08-17 ~22:20 Kyiv
- **ONE program: vacmaker v3 = WHALE CLONE (twapedge.py whale_loop), SEVEN
  coins LIVE** (eth bnb btc sol xrp hype doge — doge added 08-17), zero
  paper pods. Continuous taker tl∈[3,30]: 0.4s scan, recon ≥0.5bps + cov
  ≥0.5, fav ask 0.55–0.99, $8 FAK clips, 1s cooldown, $16/bar ladder
  (real max 3 clips ≈ $24 — check is spent<16 pre-fire), SNIPE post-close
  lane ON (≤0.99/$8/90s, ZERO fills so far), maker-rest OFF. Deviations
  from pure clone: $15/day halts + recon gate (agreed) + our band floor
  0.55 (HIS pre-close floor is 0.94 — see notes §26).
- **08-17 evening: WHALE_LADDER_MIN_ASK=0.94** — ladder clips ≥2 only at
  ask ≥0.94 (all 3 loss bars were laddered mid-band; marginal clips ≥0.94
  ran 16/16). Live on 6 coins since 18:55 UTC; **hype HALTED −$27.59 on
  OLD code — redeploy at UTC 00:00 rollover** (restart earlier would
  un-halt it; see notes §26 MUST-DO).
- Day 08-17 (cumulative ledger, pod counters reset on restarts): ≈ −$20.3
  — eth +14.2 (19W/0L), hype −27.6 (halted), btc −12.6, rest small green.
  Wallet $76.25 reconciled. 3 loss bars all mid-band weak-est laddered;
  halt overshoot: in-flight clips sail past the $15 line (hype −27.6).
- Whale overlap (whalecmp, 3h): 7 BOTH / 14 him-only / 10 us-only; same
  side every shared bar; we're earlier+cheaper (T−28 vs his T−11), he's
  deeper+broader. Settle pipeline hardened 08-17 (wait_for 25s + per-bar
  try/except after the 50-min freeze, ledger #16b/#17).
- Execution stack unchanged underneath: prewarm neg-risk, EIP-712 presign,
  FAST_EXEC, retry-FAK w/ 0.03 chase cap (legacy lane OFF while whale on),
  vol CAP_TABLE dormant (flat 0.99 cap per clone). Coverage-floor rule:
  (62−tl)/59 − slack. deploy.sh applies crypto.secret.yaml LAST (caps $8
  order / $15 day — keep in sync!).
- **08-17 ~22:45 Kyiv: recorders DRAINED to local disk** — 1,666 gz
  (2.2 GB) pulled from all 12 mrec pods, each byte-size-verified +
  fully decompressed + all 259.8M lines JSON-parsed, then deleted
  pod-side (PVCs 2.2 GB → ~370 MB; only the live hour remains, still
  recording). Local archive now 07-30 → 08-17, 4.8 GB — see §3.
  ⚠️ tar-over-`kubectl exec` TRUNCATES (65 MB of 68 MB, silently) —
  pull per file with a size+gzip check, script `scratchpad/pull_one.sh`.
- **08-18 ~09:45: TIME-SCALED GATE DEPLOYED (user "ship it")** — the §28
  fix is LIVE on btc/eth/sol/xrp/doge/hype: eff_thresh = 0.5 +
  0.035·max(0, tl−14) bps (≈1.05 at T−30 → 0.5 at T≤14), applied in
  whale_loop AND retry-FAK re-checks; env pmTeThreshSlope/Anchor;
  PF_TE_START logs both. Era replay (live fills): blocked set −$27.75
  incl ALL 9 losses; counterfactual wallet ≈$98 vs actual $70. eth
  weak-cell was 36W/0L (+$14.54) — uniform gate anyway (n too small to
  exempt; revisit on gated-era logs). **bnb gated too at ~09:55 (user override "deploy bnb as well")** —
  restart wiped its −$17.15 halt latch by design; fresh $15 budget for
  the rest of 08-18 with the gate live (rollover monitor cancelled).
  First gate-era
  losses 08-18 morning: bnb ×3 −$18.6, xrp −$7.92 — all in the cell.
  §29 (dog-side mean reversion in the cell): CLOSED negative same
  morning (dog premium 2-4× true flip; scalping strictly worse).
- **08-17 late: FLIP LOSSES DIAGNOSED (notes §28)** — the loss driver is
  entry TIME × |est|, not the ask band: our T−28 median fill with a flat
  0.5bps gate sits at a 3.1% live (10.1% proxy) flip rate vs 0.0-0.6% at
  the whale's T−11; 72% of our clips are in that one −EV cell.
- **08-18 ~12:15: REWFARM SHELVED + NAMESPACE CLEANED (user: "vac fleet
  only")** — rewfarm go-live declined, paper pods removed; 17 trader
  releases uninstalled (mintsalvage×6, twapedgelive×6, pennymint,
  poolfarm1h, vacuum, rewfarm4h×2 — only the rewfarm pair still had
  running pods). Zero orphaned CLOB orders verified. Namespace now:
  7 vacmakers + 17 mrec recorders + sweeper. mrec4h keeps recording;
  rewfarm revivable via chart/bots/*_rewfarm4h.yaml before Aug 31.
  (08-17 23:33 context: 5m/15m in-band farming measured DEAD, 4h was
  the surviving thesis — [strat-rewfarm](strat-rewfarm.md).)
- zec: market EMPTY (tripwire mrec only). Monitoring: monitor b8enlux1l
  (7 pods: whale orders matched, settles, halts, snipe fills, errors) +
  30-min check prompts; wallet 0xdb66d896. Resume path: this §2 → notes
  §25-26 → memory every-tick-single/vacmaker-twap-taker.md.

## 3. DATASET INVENTORY — check WINDOW COVERAGE before simming!

| dataset | where | coverage | valid for |
|---|---|---|---|
| `kl/ex/btc-postI.pkl` (+eth,sol) | scratchpad | ⚠️ **LATE-WINDOW snaps only (tl≲75s)** + full-bar itrades | late-window sims ONLY. Full-bar MM/ask sims on it are INVALID (clairvoyant) — this bit us 2026-08-13 |
| `kl/ex/btc-1h.pkl` | scratchpad | full-bar 1s snaps + trades, 88 bars, 91%-UP week | any 1h sim (trend-week bias noted) |
| `/tmp/btc-5mfull.pkl` | btc-mrec pod | full-bar 1s snaps + prints, ~2k bars (built 08-13) | the honest 5m sim dataset |
| **mrec raw — ⭐ CHAINLINK from 2026-08-21 19:25 UTC** | all mrec pods | rows now carry `cl` (chainlink point px), `cl_ts` (1Hz tick id — dedupe, snaps repeat ~10x), `tw` (TWAP-60) | ⭐ **the ONLY valid basis for TWAP-recon research.** Binance `lead_bps` is a PROXY that diverges ~3.7 bps median from settlement — larger than the 0.5-1.5 bps signal — which is why the proxy backtest scores the LIVE, PROFITABLE 5m vacmaker at −$232 (ledger #19). ⚠️ `run_rtds()` DEFAULTS to `twap_thirty` = WRONG stream (all coins settle TWAP-60); pass topics explicitly. `rtds.ingest` does NOT normalise symbol case. BONUS: hype/zec (no Binance spot) are backtestable for the first time |
| **mrec 5m raw — LOCAL ARCHIVE** | `every-tick-single/data/mrec/<coin>/` | ⭐ **07-30 13:00 → 08-17 18:59 UTC, gapless** (btc/eth/sol/xrp/doge/bnb ~384-399 hourly gz each; hype+zec from 08-14 21:00), 4.8 GB | the ground-truth dataset for every 5m question. Drained from the pods 08-17 (all 1,666 files byte-verified + 259.8M lines parsed, then deleted pod-side) |
| mrec 5m raw | pods, 7d rolling | 100ms everything incl next1-3 pre-open + RES | ground truth; JSON is COMPACT (`"trd":[[` no space!). ⚠️ **hype/zec rows carry `spot:0.0, lead_bps:null`** — not on Binance, so NO offline recon possible for them |
| mrec15m raw (btc, eth) | pods, since 08-13 13:10 | 100ms full | 15m questions |
| mrec15m/1h/1d — LOCAL | `data/mrec/{btc-mrec15m,eth-mrec15m,btc-mrec1h,btc-mrec1d}/` | 15m from 08-13; 1h/1d 07-31 → 08-17 (1d has a 21h hole 08-15 17 → 08-16 13, absent on the pod too) | as below |
| mrec1h / mrec1d raw | pods, 7d rolling | 100ms; ⚠️ NO RES rows (recorder predates the RES fix) — derive wins from post-role book (ub>0.5, validated 88/88 vs spot) | 1h/1d questions |
| **mrec4h raw** | pods (btc/eth/sol/xrp/hype), since 08-17 23:27 Kyiv | 100ms, files `<coin>-mrec4h-*` | 4h rewfarm ground truth (no earlier 4h data exists) |

⚠️ **15m archive naming**: the 15m pods write `<coin>-mrec-*` (NOT
`<coin>-mrec15m-*`; the writer suffix map lacked 900) — distinguish by
DIRECTORY `data/mrec/<coin>-mrec15m/`. A wrong glob = silent zero
(ledger #21).

## 4. SIM-VALIDITY CHECKLIST (every one of these caught a real error)
1. **Dataset window ≥ sim window?** (postI trap above.)
2. **Zero-count ⇒ histogram the raw before concluding.** (whitespace-filter
   bug produced a false "pre-open dead" + a tidy wrong mechanism story.)
3. **Queue haircut must REDUCE PnL for a +EV candidate.** If stricter fills
   help a supposedly-profitable maker, the fill model is broken. (For a −EV
   maker the sign legitimately flips — through-prints are the most toxic
   fills, so fewer fills can mean less loss. Refined 08-13 after the
   mm2_stream controls.)
4. **Win% flat while profit rises with depth = fill-model artifact**, not
   edge (deep fills must win less under adverse selection).
5. **Delay-insensitive PnL = clairvoyant** (dual-ask lesson).
6. Backtest vs live divergence: trust live; paper under-fills (no queue
   position) and over-forgives (no atomic sweeps).
7. Cross-check every new sim against its neighbors — two sims disagreeing
   by orders of magnitude on the same data means ≥1 is broken.

## 5. STANDING OPS RULES
- Live deploys need explicit user confirmation; risk-TIGHTENING is
  pre-authorized. Sticky per-UTC-day halt + per-side inv caps mandatory.
- No mid-bar pod restarts (in-memory inventory → re-buys) until on-chain
  reconcile exists.
- Deploy = rsync + helm (helm alone ships env not code); verify with grep
  in the pod. Live values: `helm get values <release>`.
- Monitoring: problem-monitor (Monitor tool, spam-proof filter) + cron
  checks reading `logs-training-events.jsonl*` (incl .gz rotations).
- Accounting: WALLET is truth (balance.sh + data-api positions), never bot
  counters (restart wipes). Report net worth = free + position value.

## 6. All files
[backtesting.md](backtesting.md) — ⭐ sim framework: script inventory, conventions, BUG LEDGER (append every sim bug); repo skill `/sim-validity` loads the discipline on demand ·
[commons.md](commons.md) — shared modules, mint/merge, venue rules, traps ·
[strat-poolfarm-5m](strat-poolfarm-5m.md) · [strat-poolfarm-1h](strat-poolfarm-1h.md) ·
[strat-poolfarm-15m](strat-poolfarm-15m.md) · [strat-preopen](strat-preopen.md) ·
[strat-rewfarm](strat-rewfarm.md) ·
[strat-ask-ladders](strat-ask-ladders.md) · [strat-mm-flip](strat-mm-flip.md) ·
[strat-taker-rebates](strat-taker-rebates.md) · [strat-openmm-5m](strat-openmm-5m.md) · [strat-dipbuy](strat-dipbuy.md) · [strat-reversion](strat-reversion.md) · [wallet-sylldra-0xfd9b7636](wallet-sylldra-0xfd9b7636.md) · ⭐[maker-program-2026-08](maker-program-2026-08.md) (COMPLETE RECORD) · [../MINTSALVAGE.md](../MINTSALVAGE.md) ·
[../TWAPEDGE.md](../TWAPEDGE.md) · [../RESEARCH-LOG.md](../RESEARCH-LOG.md) (chronological ledger)

## 7. Program accounting
$148.91 (08-12 top-up) → $92.05 (08-13 16:44). Detail in RESEARCH-LOG.
