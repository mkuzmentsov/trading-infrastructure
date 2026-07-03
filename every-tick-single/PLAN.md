# every-tick-single — Polymarket maker-rebate quoting bot (single-asset)

## 0. STATE OF KNOWLEDGE (2026-07-03, after one full live day) + NEXT TEST

**Scope**: this project = SINGLE-ASSET bot — ONE resting maker bid per bar per coin.
(The two-sided pair bot lived in every-tick-both — deleted after the live verdict:
−$59/$116 in a day; no +EV regime subset at 0.48/0.48; pair income +$0.40/bar could
not cover single-fill adverse selection ~−$4.4/bar at observed both-fill rates.)

**What one live day + ~400 paper bars established (hard findings):**
1. **Fill = adverse selection** (Glosten-Milgrom, measured direction-neutrally by the
   alternate-side fleet): conditional win rate of a filled 0.48 bid was **~25% in
   trending hours** and **~58-80% in chop hours** vs the 48% breakeven. The fill only
   happens when the market trades down through the bid — WHICH regime it happens in
   decides everything.
2. **Regimes cluster** (30-90 min runs of chop/trend; see regime charts: per-coin p60/p85
   thresholds on 5m |move|). A prev-bars gate is feasible; it must react within ~1-2 bars.
3. **No side signal at bar open**: p_up ~0.5, raw outcomes ~coin-flip (45.5% reversal,
   n=121). "Always-UP looked good" was up-drift beta (54% at 07:00 UTC, 0% at 11:00).
4. **Deeper entry = lower breakeven** (q needed = P) but measured q collapses faster than
   P in bad regimes (0.3-bucket won 22%). Depth is only a cushion INSIDE chop, not a fix.
5. **Rebates are garnish**: realistic $2-8/day at $5 size; ~10-100x smaller than
   adverse-selection cost per share. They ride on any +EV config; they rescue none.
6. **Ops traps**: Polymarket reports cross-token maker fills in complement terms (clamp
   to limit price); CTF shares credit with lag/dust (size sells from exchange balance);
   ankr RPC now needs a key -> use polygon-bor-rpc.publicnode.com or redemptions die.
   postOnly=True on GTC = hard maker guarantee (rejects crossing orders).

**THE NEXT TEST (run when snapshots span a full session cycle, >=1 day):**
Candidate profitable config: **rest at P in [0.45-0.48] ONLY in chop-classified bars,
hold to expiry, collect rebates.** Decide with the snapshot grid (bar_snapshot events,
15s book states, all 4 coins since 2026-07-03 ~11:00 UTC):
- Measure **q(P | regime)**: hypothetical fill (book ask crossed P) -> outcome win rate,
  per price level per regime class (per-coin p60/p85 rolling thresholds).
- GO if q(P | chop) - P >= +5pp with n >= 150 fills and the gate's regime classification
  is implementable from data available AT THE BAR OPEN (prev bars only, no lookahead).
- Also grid: exit rule (cut if unrecovered at T) vs hold-to-expiry — recovery curves
  from snapshots; conviction side-rule (p_up logged per bar) vs alternate.
- Grid script pattern: join bar_snapshot <-> paper_bar_settle on condition_id ==
  paper_condition_id (settle's market_start_ts is the NEXT bar's — trap).
Go-live only after the gated config shows +EV **including** its trend-hour mistakes
(gate lag bars), at $5 size, on a fresh out-of-sample day.

Per-coin instances: `btc-every-tick-trader`, `eth-every-tick-trader`, … Source ported from
`polymarket/k8s/helm/polymarket-btc-5m-bot` (the math_smart 5m taker bot); this project flips
the role: **be the maker, not the taker** — quote every 5m tick, collect spread + maker rebates.

## 1. The rebate program (verified from Polymarket docs, 2026-07)

- Takers pay a category fee; **crypto = feeRate 0.07** (highest; ~1.8%/100 shares cap).
  Makers pay nothing.
- **20% of crypto taker fees** go to a daily maker-rebate pool, split **per market**,
  proportional to each maker's filled-order weight:
  `fee_equivalent = shares × feeRate × p × (1−p)`
- **p(1−p) peaks at p=0.50** → a fill at 50c carries 0.25 weight vs 0.09 at 90c — **~2.8×
  more rebate weight near 50c**. This is the "more rebates near 50c" effect (it's the weight
  formula, not a separate bonus).
- Paid daily in pUSD, min $1 accrued. Only FILLED maker orders count.

## 2. Why this can be profitable (and what kills it)

Three PnL streams per bar:
1. **Two-sided lock:** bid UP at `b_u` and DOWN at `b_d` with `b_u + b_d < 1`. If BOTH fill,
   the pair settles at exactly $1 → locked profit `1 − (b_u + b_d)` regardless of outcome.
2. **Rebates** on every filled quote (max weight near 50c — exactly where a 5m bar opens).
3. **Spread capture** on one-sided fills that mean-revert.

### 2b. v1 live mode: ONE-SIDED hold-to-expiry (current)

Rest a single bid per bar (`QUOTE_MODE=one_sided`, side=`cheaper` — the ≤50c side, max
p(1−p) rebate weight, least $ at risk), hold any fill to expiry. The math:
**EV per share = q − p** (q = the fills' realized win rate, p = fill price). If fills are
unbiased (q ≈ p), directional PnL ≈ 0 and **rebates are pure profit**. The rebate is at most
~0.35c/share at 50c (20% × 0.07 × 0.25, assuming the whole pool), so the strategy survives
only if adverse selection keeps q within ~0.7pp of p. Paper logs measure exactly this:
q-vs-p per price bucket from `paper_fill` + `paper_bar_settle` events.

**Backlog:**
- ⭐ **HIGH PRIORITY — pair-incomplete exit rule** (analyzed 2026-07-03 on first 24 live
  btc bars; revisit with more bars): two-sided @0.48 economics = 18 BOTH bars ALL won
  (avg +$0.40 lock) vs 6 SINGLE-fill bars ALL lost (−$4.75) → net −$16.5. Single-fill
  breakeven needs q≥35%, observed 0/6. Second-side fill time in BOTH bars: 33%≤30s,
  50%≤60s, 83%≤120s (median 60s); lone fills arrive ≤11s, so the only signal is the
  second side's absence. Rule: if pair incomplete at T≈120s (sacrifices only ~3/18
  late pairs, catches all singles), exit the filled side. Variants: (a) FREE maker
  exit at ~entry 0.48-0.49 — fills on recovery only, needs pair-state machine so a
  filled exit + late second fill doesn't leave a naked position; (b) taker cut at
  T≈120-180s into the bid (~-1..-2 instead of -4.8; a stop by another name, but
  conditional population ≠ the 10c-touch study that killed stops). DECIDE with:
  P(filled side recovers to ≥0.48 | pair incomplete at 120s) from paper book
  snapshots — ≥~40% → maker exit suffices; ~10% → only taker cut works.
- A/B the `two_sided` pair-lock mode (quote both tokens, both-fill locks 1−(b_u+b_d)
  risk-free) against one-sided — e.g. run 2 coins per mode over the same week and compare
  net PnL after adverse selection. The two-sided code is implemented and config-gated.
- **Stop-vs-no-stop recovery analysis** (bracket mode): the 10c taker stop saves 10c/share
  on truly-dead bars but costs 90c/share whenever a 10c-toucher recovers to win —
  breakeven recovery rate ≈ 10%. From paper logs, measure P(win | position touched
  STOP_LOSS_PRICE): join `paper_stop_fired` events against the bar's final outcome
  (and, for no-stop counterfactual, bars where the mark dipped ≤ 0.10 but settled a win).
  If recovery > ~10%, drop the stop (hold to expiry); if ≪ 10%, keep it. Note: a maker
  "stop" (resting sell below the bid) is impossible on a CLOB — it executes immediately
  as a taker at the bid; the only maker variant fills on recovery only, i.e. it isn't a stop.
  Taker fee at 10c is tiny anyway (0.07 × 0.1 × 0.9 ≈ 0.63%).
- **CLV (closing-line value) scoring** — from sports betting (Wong): score every paper fill
  against the bar's final pre-expiry price, not just win/loss. `clv = final_price − fill_price`
  per fill. Converges to edge-quality in hours (hundreds of fills) instead of days of PnL;
  a persistently negative CLV = adverse selection, measurable per price bucket / time-in-bar.
- **Risk-of-ruin sizing for go-live** — Chen/Ankenman (Mathematics of Poker) bankroll formulas:
  given measured per-bar edge and variance from paper, compute the bankroll for <1% ruin and
  size live bets from it (we did the same for the algo-trading leverage frontier).
- **Glosten-Milgrom quote conditioning** — a fill is evidence against you (the counterparty
  chose to trade). Ideas to test: after a fill, widen/skip the next bar's quote on that coin;
  skew the quote price by recent fill direction (inventory-aware quoting à la
  Avellaneda-Stoikov); require the book to be two-sided-deep before resting (thin opposite
  side = informed flow more likely).
- **Time-in-bar fill quality** — bucket fills by seconds-since-bar-open; if early fills are
  ~unbiased and late fills are toxic (expected), tighten the quoting window to the measured
  sweet spot instead of the fixed warmup/cutoff.
- **Persist event logs to the PVC + daily rotation** (user-requested, do AFTER go-live):
  `logs-training-events.jsonl` currently lives on ephemeral `/app/logs` and is lost on every
  redeploy. Move it to the mounted `/data` volume and rotate daily (keep ~14 days, gzip old
  days) so it doesn't eat the PVC.
- **Kelly-fraction per-bar sizing** — once p_up calibration is measured from paper logs
  (predicted p_up vs realized outcome), size entries by fractional Kelly on the calibrated
  edge instead of fixed QUOTE_SIZE.

The killer: **adverse selection late in the bar** — informed flow (our own old math_smart bot
was exactly this taker!) hits stale quotes when the BTC move is already known. Mitigations
are the core of the strategy:
- **Quote early** (first minutes, p≈50c: max rebate weight, flow is mostly uninformed).
- **Hard cutoff**: cancel all quotes at T−`quoteCutoffSecs` (default 60s) — never rest quotes
  in the sniping window.
- **Reprice on movement**: cancel/replace when BTC moves > z threshold (reuse the bot's
  z/sigma machinery) so quotes never go stale mid-bar.
- **Inventory cap** per bar per coin; filled inventory holds to expiry (5m settle) in v1.

## 3. Paper mode (this phase)

No real orders. A paper engine simulates our resting quotes against the LIVE book/trade feed:
- Our bid at P fills when the market prints a trade at ≤ P (or the book crosses our level),
  fill size capped by printed size. Conservative by design.
- Settlement at bar expiry using the actual outcome.
- Logs (jsonl, same pipeline as before): quote lifecycle, paper fills (with fee_equivalent),
  bar settles (PnL split: two-sided lock / directional / rebate est.), daily rebate estimate.
- **All available 5m coins** (BTC/ETH/SOL/XRP per gamma discovery) for maximal log volume.

Rebate estimate honesty: the actual rebate depends on OTHER makers' fee-equivalent in the same
market (proportional split). Paper logs the fee_equivalent numerator; the realized pool share
is only knowable live. Treat paper rebate numbers as upper bounds.

## 4. Success criteria to go live

- ≥1 week of paper across all coins.
- Two-sided fill rate, one-sided adverse-selection loss, and net PnL per bar ≥ 0 **before**
  rebates (rebates then are pure upside), or clearly ≥ 0 after conservative (50%-haircut)
  rebate estimates.
- Live starts tiny ($1–5 quotes) on BTC only.

## 5. Layout

- `src/` — bot source (ported; new: `strategies/maker_rebate.py`, `paper_book.py`)
- `chart/` — helm chart (per-coin values files)
- `Dockerfile`
- research/sweep scripts stay in `chart/` root for now (from the old project)
