# Backtesting & simulation — framework knowledge, bug ledger, conventions

Updated 2026-08-13. Read BEFORE writing or debugging any sim. Companion to
docs/README.md §3 (dataset inventory) and §4 (validity checklist).

## 1. Sim script inventory (scratchpad kl/ unless noted)

| script | tests | dataset | status |
|---|---|---|---|
| `pf_bt2.py` | chase vs no-chase poolfarm | rebate_arb cache (pre-TWAP, full prints) | valid for fill economics |
| `pf_bt_ceil.py` | pair ceiling, vol-gate, mid-band, predictive pull | postI (late-window) | valid ONLY for late-window questions |
| `pf_bt_paired.py` | vol gate + unwind | postI | same caveat |
| `pf_bt_complete.py` | reactive maker completion | postI | same caveat |
| `pf_bt_batch.py` | batch pairs (imbalance throttle) | 1h full-bar ✓ / postI ⚠️ | 1h numbers valid; 5m = late-window only |
| `pf_bt_mm.py` | single-token intra-bar flipping | 1h full-bar | valid (dead verdict) |
| `pf_bt_dur.py` | duration-generalized pairs | postI / 1h | 1h valid; 5m late-window |
| `pf_bt_mm2.py` | two-sided skewed MM + mint/merge | 1h valid (−$70/day); postI run INVALID | superseded by mm2_stream |
| `mm2_stream.py` | same MM, streaming in-pod on RAW (full-bar) | mrec raw 7d | THE honest 5m runner |
| `ext2.py` | extract postI (LATE-WINDOW snaps + full-bar itrades) | mrec raw | note the window! |
| `ext1h.py` | extract 1h FULL-BAR 1s snaps | mrec1h raw | good template |
| in-pod one-liners | pre-open scans, holder scans | raw / APIs | see bug ledger #1 |

## 2. Conventions (all sims)
- Snapshots sorted by tl DESCENDING = time order. Fill window per snapshot =
  prints with tl in (next_snap_tl, this_tl]. Trades stored as (tl, tok, px,
  sz, side); mrec trd rows give ts → tl = BAR − (ts − ws).
- Maker fill rules: our BUY at b fills on a taker SELL print px ≤ b (−QH);
  our SELL at a fills on a taker BUY print px ≥ a (+QH). QH = queue haircut
  ($0.01 = one tick through) — stricter QH MUST lower PnL (see ledger #4).
- Windows: respect QUIT_TL (stand-down before close: 45s@5m, 75s@15m,
  60s@1h) and WARMUP after open. Mid sanity: 0<bid<ask<1.
- Outcomes: RES rows (mrec) or post-role book (ub>0.8 ⇒ UP); always
  cross-check derived wins vs spot trajectory on a sample.
- Dedupe prints across snapshot rows: key (ts, tok, px, sz) into a set.
- Economics: matched-pair component vs one-sided residual SEPARATELY —
  aggregates hide which one drives PnL (residual luck on trend weeks is the
  #1 false-positive source; 91%-UP week in the 1h dataset).

## 3. BUG LEDGER — symptom → cause → fix → prevention (append every new one)

1. **2026-08-13 whitespace prefilter.** Symptom: zero pre-open prints across
   2,034 bars → clean-looking "structurally dead" verdict. Cause: filter
   `'"trd": [['` (space) vs compact raw `"trd":[[`. Fix: match both / parse
   all SNAP lines. Prevention: any zero-count ⇒ histogram raw WITHOUT the
   filter first; a tidy mechanism story is not evidence.
2. **2026-08-13 dataset-window mismatch (postI).** Symptom: skewed-MM sim
   +$1,635/day on 5m (vs −$70/day on 1h full-bar). Cause: postI snaps cover
   only tl≲75s while itrades span the full bar → quotes from stale mids
   matched full-bar prints = clairvoyant. Fix: full-bar extract (mm2_stream
   on raw). Prevention: check dataset coverage vs sim window BEFORE running
   (docs/README §3 table).
3. **2026-08-13 flat-level strawman.** Symptom: flat-ask ladder −$2,618/day
   contradicting neighbor sims. Cause: flat price level matched against
   full-bar prints (sells the runaway winner at 0.52 all bar). Fix:
   mid-relative quoting. Prevention: never model an adaptive strategy with
   a static price.
4. **Fill-model optimism signatures.** (a) queue haircut IMPROVES PnL ⇒
   broken model (it filters to better-priced fills without the queue cost);
   (b) win% pinned flat while profit rises with depth ⇒ artifact (adverse
   selection must lower deep-fill win%); (c) delay-insensitive PnL ⇒
   clairvoyant (dual-ask 2026-08-02 lesson).
5. **In-pod OOM (exit 137).** Symptom: background scan dies silently with
   exit 137. Cause: accumulating per-bar print sets over 7d (millions).
   Fix: streaming finalize-as-you-go (mm2_stream pattern: finalize bars
   older than maxws−1800 every N files; only accumulators persist).
6. **zsh subscript eats $c[...]** in inline python via kubectl exec.
   Fix: pass values via `env COIN=$c` + single-quoted heredoc/stdin script.
7. **Log rotation truncates history.** logs-training-events.jsonl rotates
   per UTC day (.gz) — cumulative stats must read `*.jsonl*`; a "since last
   PF_MM_START" filter drops pre-rotation bars silently.
8. **Gamma 403s / closed markets.** Needs browser User-Agent; closed slugs
   need `&closed=true` (empty result otherwise, looks like "not found").
9. **Paper vs live fills.** Paper under-fills (no queue position; 2.5h
   zero-fill paper vs minutes-to-fill live, 2026-08-13) and can't reproduce
   atomic adverse sweeps. Paper validates plumbing, never EV.
10. **truncated gz mid-pull** (kubectl cp/tar) ⇒ EOFError kills naive loops.
    Wrap per-file try/except (EOFError, OSError, BadGzipFile).
11. **2026-08-14 maker backtest without QUEUE modeling.** Symptom: mintsalvage
    revalidation forecast +$2-5/day; live gave 0/27 fills. Cause: measured
    the FLOW at the price level (411k sh/day at 1¢) and the RISK (flips) but
    not the STANDING QUEUE ahead of us (median 942sh / p75 4,566sh at t−45)
    — and transplanted doc-era (thin-queue regime) fill rates. Fill
    probability for a resting order = P(flow_after_join > queue_at_join);
    regime changes move the QUEUE first. Fix/prevention: any maker-fill
    backtest MUST simulate join-time book depth + FIFO consumption
    (kl-pattern: capture depth at placement moments + subsequent executions,
    fill iff flow > queue + our size). Doc-era fill rates never transfer
    across a structural venue change.
12. **2026-08-14 wrong venue-field as capability indicator.** Symptom:
    claimed "1h pays no maker rebate" from makerRebatesFeeShareBps=None;
    the Polymarket UI shows a Maker Rebate badge on hourly markets and
    feeSchedule.rebateRate=0.2 was present all along (user caught it via
    screenshot). Cause: treated an auxiliary field as the flag. Fix: the
    operative rebate indicator is feeSchedule.rebateRate (+feesEnabled);
    verify capabilities against the venue UI when fields disagree.
    Prevention: two independent confirmations before declaring a venue
    capability absent (fields + UI/docs/payment history).
13. **2026-08-15 zsh no-word-split on `for c in $group`.** Symptom: two of
    three parallel scan groups produced EMPTY output files, silently. Cause:
    zsh does not word-split unquoted vars — `c` iterated once with the
    literal "eth sol". Fix: single-item loops, `${=group}`, or bash arrays.
    Prevention: after any fan-out, check every output file is non-empty
    before reading conclusions from the survivors.
14. **2026-08-15 spot-lead proxy contaminates cheap-band cells.** Symptom:
    btc <0.80 band +$148 while bnb <0.80 −$114 with avg entry 0.09-0.55 —
    "leader" asks at 9¢ mean the MARKET disagrees with the spot-lead sign,
    i.e. near-tie bars where Binance lead ≠ TWAP settlement (the old
    binance-chainlink-divergence lesson). The offline surface is VALID for
    decisive bands (≥0.95) and NOT decisive for cheap bands — those need the
    true TWAP-60 reconstruction signal (the live vacmaker sweep's job).
15. **2026-08-15 dead WS manufactures a winning paper day.** Symptom: eth
    vacmaker sim booked +$2.99@0.61 and +$2.05@0.73 "wins" 16:29-17:27 UTC
    while every live FAK was killed. Cause: the PM book WS went
    event-starved (heartbeat events=2, quote age 150s) but kept its last
    top-of-book — the paper lane "filled" phantom stale asks; live FAKs
    (reality check) all died with "no orders found to match". Fix: pod
    restart revived the feed; those sim rows EXCLUDED from all tallies.
    Prevention: gate paper fills on BOOK FRESHNESS (quote age < a few s,
    event rate sane); in any paper-vs-live divergence, matched=False lines
    are the ground truth — filter sim rows to bars whose live order
    matched, or whose heartbeat showed a flowing book.
16b. **2026-08-17 settle-loop freeze: unbounded await in a for-loop.**
    Symptom: no settles fleet-wide for 50 min while orders kept filling;
    wallet looked down $50 (all of it in unswept winning positions). Cause:
    one gamma urllib call hung past its timeout inside settle_loop's bar
    iteration — every later bar queued behind it. Fix: asyncio.wait_for
    around the lookup + per-bar try/except + SETTLE_ABANDONED event.
    Prevention: any per-item await in a serving loop needs a hard outer
    timeout; "the library has a timeout" is not a guarantee.
16. **2026-08-16 survivor bias in "the no-fills all would have won".**
    Symptom: 11/11 killed FAKs settled our way → "resting GTC instead would
    have captured them". Cause: observed no-fills CONDITION on the signal
    having held to the bell; bars where the ask vanished AND the signal
    later flipped produce no order event at all — invisible in the logs —
    and those are exactly the bars a resting bid WOULD have filled (informed
    sellers hit resters at the start of the flip). Fix: retry-FAK
    (re-check signal each attempt) captures the refill upside with taker
    control; GTC rejected. Prevention: before averaging outcomes over an
    event set, ask what conditioned the set's visibility.

## 4. Streaming in-pod sim template
`kl/mm2_stream.py` is the reference: parse raw → finalize bars past a
watermark → run N configs per bar → accumulators only. Always include a
no-op/control config (K=0, QH=0) — controls catch model bugs (§3.4) from
inside the run itself.

## 5. Where results go
Every sim run: one line in RESEARCH-LOG.md (date, dataset, configs, numbers,
verdict) + update the strategy's doc + flip the docs/README decision-map row
if the verdict changed. A sim whose result isn't written down didn't happen.
18. **2026-08-17 "no tiers" — repeat of #12.** Symptom: told the user
    Polymarket has no volume tiers after reading only the per-market
    feeSchedule. The Taker Rebate Program (7 tiers, wV-based) lives in
    docs/programs/*, a different layer than market objects. User caught
    it via a screenshot AGAIN. Prevention (#12 restated, stronger): a
    venue capability is "absent" only after checking BOTH the API object
    AND the official docs (docs.polymarket.com/llms.txt is greppable);
    program-level features are never in per-market fields.
19. **2026-08-17 the Binance-spot recon proxy is biased ~2-3× PESSIMISTIC on
    flip rate.** `tools/swing.py` recons the settlement TWAP from the mrec
    recorder's Binance-spot `lead_bps` mean; the bot recons the Chainlink
    TWAP-60 stream. Same cell (|est| 0.5-1.0bps, ~T−25): proxy 8.5-10.1%
    flip vs **3.1% measured on our own live logs** (5/160). The SHAPE
    (monotone in |est| and in tl, per-coin ordering) matches; the LEVEL does
    not. Rule: quote the proxy for structure/per-coin comparisons, quote live
    event logs for any number that sets a threshold or an EV. Sibling of the
    [[binance-chainlink-divergence]] rule — near-tie bars are exactly where
    the proxy invents flips.
21. **2026-08-17 15m-archive prefix mismatch → silent all-zero result.**
    Symptom: btc/eth 15m sim rows all zero in the grid aggregate, looking
    like "no edge". Cause: globbed `<coin>-mrec15m-*` but the 15m pods
    write `<coin>-mrec-*` (writer `_SUFFIX` map lacked 900); glob matched
    nothing. Fix: prefix `<coin>-mrec` for all sub-hourly, distinguish by
    directory. Prevention = #13 restated: any zero row in a fan-out output
    is a BUG until the input file list is shown non-empty.
22. **2026-08-17 reward-scoring sims: the adjusted mid INCLUDES our own
    orders.** An improving quote moves the midpoint toward itself — scoring
    it against the pre-existing book mid credits w=1.0 instead of the real
    0.44 (2.25× reward inflation). Model the effective book (ours merged)
    before computing spreads-from-mid.
20. **2026-08-17 "accuracy" must be conditioned on BUYABILITY.** Ambient
    accuracy in the |est| 0.5-1.0 cell is ~97% over all bars but **92.1%
    (n=239) on bars where an ask actually existed below 1.0** — the ask
    appears precisely when the book disagrees with us. Any EV table built on
    all-bars accuracy overstates a taker strategy by ~5pp in the weak cell.
    Always cut EV on the fills-possible subset.

## Bug #23 — a displayed cheap ask is NOT takeable (the binary book is ONE book)

2026-08-23, §41. `ua ≡ 1 − db` and `uas ≡ dbs` in **100%** of recorder rows
(btc 31,534 · eth 30,553 · doge 31,893) — the UP ask IS the complement of the
DOWN bid. So "buy the dip at 0.60" means hitting a resting DOWN bid at 0.40,
i.e. taking the other side of an informed maker who pulls the moment the move
that creates our signal is visible. Live proof: FAK match rate **11.2%** at a
seen ask of 0.55–0.75 (295 attempts, `LIVE_ERR`=0, price paid ABOVE the seen
ask, 9sh against 40–50sh displayed) vs **75%** at >0.98. Any sim that books a
fill because the snapshot showed an ask overstates the cheap bands ~7×
(simulated +15.8% ROI for 0.55–0.75 vs +2.1% live).
**Prevention:** price-band results must be discounted by the band's MEASURED
live match rate before they are called an edge; `tools/fillphys.py` prints it.
Corollary for the >0.98 lane: those fills exist because the §27 1¢-lottery
bidders on the loser side do NOT pull.

## Bug #13 — the STRIKE is the TWAP at bar open, not the spot at bar open

5m/15m markets settle by comparing the final TWAP-60 to a strike that is itself
`rtds_state.twap_at(SYM, ws)` = mean over **[ws-62, ws-3]** (`twapedge.py:566`).
Using spot-at-open instead scored the known-profitable 5m lane at **-2.40% ROI**
(87.8% win at median ask 0.980). Corollary: the strike window lies BEFORE the bar
opens, so a series keyed per-bar cannot see it — build ONE continuous per-coin
spot series across bars, then slice.

## Bug #14 — scan the whole tl window; never sample one snapshot

Taking a single snapshot (e.g. `sorted(snaps)[-1]`) instead of scanning tl 14->3
the way the live loop does fabricates missing liquidity: any one snapshot carries
an ask on a given side only ~52% of the time, so single-sampling reported
`ask_none` on 97% of bars and declared 15m untradeable for the wrong reason.

**Validity check that caught both:** the 5m lane is profitable LIVE, so any harness
scoring it negative is broken — and after fixing, a correct harness is MONOTONE in
the margin gate (79.4%/+2.67% at >=1bps -> 100%/+16.28% at >=3bps). Gate-ordering
monotonicity is a free correctness test; if it is not monotone, doubt the harness.


**Bug #13 (2026-08-26, §46): min/max-over-outcome-window bucketing is
hindsight.** Scoring bars by the minimum ask they reached inside the
window silently conditions on the path's future (a dip that bounced vs
one that kept falling). Symptom: spectacular win rates in a "cheap"
bucket that first-touch replay collapses to breakeven (87% → 51%).
Rule: any entry-price study must be replayed as FIRST-TOUCH on the
100ms path, at the touched price, one trigger per bar — never on
per-bar extremes. Also re-check for single correlated episodes
(same-timestamp multi-coin rows are ONE event).

## Bug #24 — settlement-mechanics ERAS inside one archive (2026-08-29, openlag)

The local mrec archive (07-30→08-17) spans THREE resolution regimes (venue
changelog): point-price settle <Aug 7; TWAP-30 Aug 7–14; TWAP-60 ≥Aug 14.
A TWAP-60 strike recon applied to point-era bars manufactured fake
"displacement" signals (spot never diverges from a strike that IS the spot)
— win% 40-50% on ≥5bps "triggers", i.e. pure vig burn, which first read as
"signal decays" day structure. Symptom to watch: a day-split whose sign
flips at a known venue-change date. Rule: any strike/settlement study must
hard-split by era and only the current-era slice counts; the mismatched
era doubles as a free negative control (it must come out dead — ours did).
Corollary: archive data before Aug 7 is unusable for ANY settlement-window
question (the mechanism didn't exist).

## Bug #23 addendum (2026-09-01, adversarial hunt): ghost-kills at scale + the placebo control

Placebo-controlled kill-timing on 6,418 live vacmaker FAKs (pess_ artifacts,
session 09-01): (a) **taker-delay leakage REFUTED** — target-ask fade within
~150ms of submit 3.5% vs matched placebo 8.9% (z=−9.2, wrong direction);
makers do NOT see pending delayed orders. (b) **84% of our kills are
"ghosts"**: the recorder shows a matchable ask persisting ≥15s with no
consuming prints after the venue returns "no orders found to match" (60% =
the ≥0.90 tick-cross artifact; ~40% genuine mid-band phantoms). This is the
at-scale number behind the 11% cheap-fill rate and the 7× snapshot-sim
overstatement. RULES: (i) any taker EV model must discount displayed
in-band liquidity by the band's measured ghost rate BEFORE economics;
(ii) any execution-causality question should reuse the matched-placebo
design (same bars, submit±5s, no order in flight) — event-rate comparisons
without a placebo arm are uninterpretable here.

## mrec v2 calibration note (2026-09-02): RB hash-match baseline

The 30s REST-vs-WS hash reconcile matches only **~35-40% on btc** in normal
operation — NOT staleness. Mechanism: `price_change` WS events carry no
`hash`, so the recorded WS hash trails until the next full `book` event;
57% of "mismatched" rows have IDENTICAL top-of-book prices, the rest are
±0.35s churn-timing 1-2 tick diffs. RULES: (i) judge feed health on
`evage` + file growth, not hash equality; (ii) for staleness verdicts
compare TOP PRICES between RB and the nearest SNAP, not hashes; (iii) a
truly stale feed shows hash match ≈0% AND rising evage AND frozen SNAP
books — all three, or it isn't stale.

## mrec v2 fix (2026-09-03): CLOB REST /book rate-limits the reconcile

The 30s × 2-token × 17-pod REST reconcile (~68 req/min) draws **HTTP 403**
from clob.polymarket.com — only 30 of ~240 expected RB rows/hour landed, and
the surviving sample skewed the hash-match statistic (6% vs the ~35-40%
baseline). Fixed: 150s base + per-coin deterministic jitter (destaggers the
fleet), ONE token per cycle (alternating), exponential backoff to 20 min on
403/429 ⇒ ~7 req/min fleet-wide. LESSONS: (i) any fleet-wide polling of a
venue REST endpoint must be rate-budgeted across ALL pods, not per pod;
(ii) a diagnostic that silently degrades produces a WORSE signal than none —
the RB hash-rate alert was firing on its own sampling artifact. Health is now
judged on evage + file growth + RB-presence, never on hash equality.

## Bug #25 (2026-09-06): mrec-based recon sims are CLAIRVOYANT unless Chainlink ticks are lagged by the relay delay
mrec SNAP records cl/cl_ts at ORACLE timestamps; the live bot receives each tick p50 2.21s later (p99 45s). A sim that filters ticks by `cl_ts <= now` grants the strategy ~2.2s of future oracle data — at tl 20-35 mid-dislocation that decides the side. Measured impact: +$3,178/6d (sim) vs −$92/18d (live PF_TE_WHALE_DELAY ground truth) for the same early deep-ask rule. Fix: lag every tick by the recorded per-event relay delay (or +2.2s flat) before feeding the estimator; better, prefer the live DELAY-event A/B which needs no reconstruction.

## mrec v2 defect (2026-09-06, §66): `price_change` events have no market attribution

`multi_recorder._emit_raw` tags a WSE row with `ws`/`tok` from `self.tok2m[aid]`, but a PM
`price_change` message carries no top-level `asset_id` — so the lookup misses and the row is
written **without `ws`**. Measured on btc 09-05 12:00: `book` 32,680 rows (100% have `ws`),
`last_trade_price` 15,533 (100%), `tick_size_change` 44 (100%), **`price_change` 848,509 (0%)** —
i.e. 95% of the event stream is unattributable. The per-change `U`/`D` tag *is* resolved inside
`ch[]`, but "U" is ambiguous across the three tracked markets (cur/next/next2), so event-time book
reconstruction is impossible from these rows.

IMPACT: any event-time analysis must fall back to the 10Hz SNAP ladders (which is what §66 did).
The raw-event stream currently buys us the trade tape and the hash chain, not sub-100ms book state
— which was one of its two stated motivations.
FIX: in the `price_change` branch, resolve the market from the FIRST change's `asset_id`
(`self.tok2m.get(c["asset_id"])`) and set `row["ws"]` from it; PM never mixes markets in one
`changes[]` array. One line, no schema change.
PREVENTION: when compacting a payload, assert that every field the *analysis* keys on survives
the compaction — write one row, read it back, and try the join before deploying the recorder.

## mrec v2 calibration note addendum (2026-09-06, §66): use PRESENCE, not the hash

Re-measured on 66,764 RB↔SNAP joins (0.2s tolerance), all 7 coins: hash `match` is 45.6% on btc
and 68-99% elsewhere — but ask **presence** agrees in **99.9%** of rows (0.07% REST-only,
0.01% WS-only), and when both are present the top-price difference is *symmetric* around zero
(median 0.000, p1/p99 = ∓0.07, our ask higher 39.8% / lower 42.0%). Symmetric ⇒ churn during the
REST round-trip, not staleness. CONSEQUENCE for research: "the favourite has no ask" readings in
the SNAP stream are venue truth and can be trusted (§66-3 rests on this); the hash rate must never
be used as a data-quality gate.

## Bug #26 (2026-09-06, §67): the replay's ask band must match the bot's real MIN_ASK

Symptom: an early-deep-ask replay (tl 20-35) read **+$270/day** against live A/B ground
truth of **−$5/day** — a sign flip, not a magnitude error.
Cause: the replay scanned `fav_ask` 0.30-0.90 while the fleet runs `PM_TE_MIN_ASK=0.55`.
The 0.30-0.55 slice the bot can never take supplied the entire profit; restricting to
0.55-0.90 alone flipped it to −$48/day, and adding tape-confirmed fills landed it at
−$20.7/day (22 fires/day, 74.2% win) vs live 30.8/day, 80.4% — calibrated.
Why it is seductive: sub-MIN_ASK displayed asks are the *cheapest* rows in the panel, so
they dominate any ROI-weighted statistic while being exactly the rows bug #23 says are
unreachable (an ask ≤0.75 fills 11% of the time, adversely).
FIX/PREVENTION: every replay must be constructed from the LIVE env values
(`MIN_ASK`, `WHALE_CAP`, `LADDER_MIN_ASK`, `FIRST_SKIP_LO/HI`, delay gate), not from a
band chosen for the analysis. Print the gate set at the top of every sim run. And keep
the §64 habit: reconcile fires/day AND win% against a live A/B before reading PnL — the
count mismatch (102/day vs 30.8/day) was the tell, before the PnL was even looked at.

## Fill-model discipline addendum (2026-09-06, §67): report the level, not the delta

A tape-confirmed fill model has two free parameters — the forward window and how far
below the displayed ask the FAK is assumed to sweep — and they move a vacmaker replay
baseline over **−$8.3 … +$35.4/day**. Narrow window + unlimited sweep is the most
contaminated corner (it is close to "always catch the windfall exactly when one exists").
RULE: when a change is evaluated against a modelled fill, sweep the full grid and report
(i) the candidate's own level across the grid, and (ii) model-independent risk metrics
(loss count, worst day, worst bar) — never a single-cell delta. A delta that only exists
in one corner of the grid is a fill-model artifact.

## Bug #27 (2026-09-06, §68): a replay's fill model must be scored against live PnL, and its sizing must match the fleet

Two independent errors, both in `tools/mrec/polysim2.py`, both found by comparing the
replay to the fleet's own day closes instead of to another replay.

1. **Sizing.** The replay ran `CLIP=8 / LADDER=16`. The live fleet runs **$24 / $48**
   (`chart/bots/*_vacmaker.yaml: pmTeWhaleLadderUsd`). Every $/day in §66/§67 is at one
   third of live scale, and the $24 clip exceeds the median top-of-book ($25.3) about half
   the time, so the sim's unlimited-size-at-top-level assumption compounds the error.
2. **Price improvement is borrowed from the future.** `fpx = min(ask, best qualifying print
   in the next W seconds)` credits us with book moves that arrive after our order would have
   landed. Measured on 10Hz ladders: ≥5¢ improvement occurs on **1.3%** of fires within 0.2s
   and **7.0%** within 1.5s. Our path is a 0.4s scan + ~200ms venue latency.

**Fix / house fill model:** window **0.4s**, price-improvement cap **0¢** (fill at the
displayed ask), size walked down the displayed **top-3** ask ladder, tape-confirmed,
CLIP=24 / LADDER=48. Scored over 09-02…09-04 (09-01 excluded — the parquet starts 09-01
20:00 UTC, so the sim sees 4h of a 24h live day), that cell is the best of twelve on all
three axes at once: **+$34.94 vs live +$18.40 (1.9×), 312 bars vs 351, 22 loss bars vs 17.**
Neighbours miss badly — (0.4s, unlimited sweep) reads **+$212.84** on the same three days, and
(1.5s, any cap) carries **34** loss bars, double the live count.
⚠️ **The calibration is aggregate-only.** Per coin the same cell is ANTI-correlated with live
(r = −0.63 on 7 coin totals, −0.28 on 28 coin-days): with ~20 loss bars and a 30:1 payoff, a
coin's PnL is decided by which individual bars flipped, and the replay's fire set is not the
live bot's. Never rank coins from a replay.

**Prevention:** a replay of a LIVE strategy has ground truth available. Score it against the
day closes in `winner-vacuum/RESEARCH-LOG.md` before reporting any number from it, and state
the cell. A fill-model "uncertainty band" that was never scored against live is not an
uncertainty band — it is an unfinished calibration.

## Bug #28 (2026-09-06, §72): a tape-CONFIRMED fill is not a tape-SIZED fill

The successor to #27 and the single assumption underneath every §66-§71 number. The replay
authorises the **entire displayed top-3 ladder** on the strength of *one* qualifying print — a
5-share print at 0.99 licenses $72 of displayed depth. Bug #23 says the displayed size is not
takeable; requiring a print proves *takeability at that price*, not *takeable size*.

**Symptom that catches it:** simulated shares exceed the total window tape on >50% of clips. At
$72/$144 sizing the sim bought **more shares than the entire window's tape**.

**Fix:** cap each simulated clip's shares at the shares that printed at ≤ our limit inside the
fill window; report capped and uncapped side by side, and a 50%-capture variant (we compete for
that volume, we do not own it).

**What it changes** (09-02…09-05 against live **+$48.39 / 474 bars / 19 loss bars**):

| | uncapped | tape-size capped | @50% capture |
|---|---|---|---|
| baseline $/day | 27.41 | **14.00** | 5.57 |
| vs live, 4 days | **2.60×** | **1.17×** | 0.28× |
| baseline worst day | −$63.36 | **−$1.59** | −$13.64 |
| losing clips/day | 4.2 | 4.2 | 4.2 |

It produced, on its own: the 2.6× calibration miss, the −$63 worst day the veto "fixes", a
monotone cap-raise that contradicted a live refutation (§65-2), the veto's 86% concentration in
the cheap band, and "MIN_ASK 0.55 beats 0.90". Correct it and the loss-clip count is the **only**
metric that does not move.

**Prevention:** put **size** in the fill grid. §68 searched fill window × price-improvement cap and
declared a winner while holding the third free parameter fixed at "unlimited".

## Bug #23 addendum (2026-09-06, §72): panel-derived availability before 09-04 is phantom-contaminated

On bars settling **|margin| ≥ 5bps**, the recorder shows 4,739 seconds of cheap (≤0.90) displayed
**favourite**-side asks across 271 bars on 09-01…09-03 at a median ask of 0.51 — and a matching
winner-side print exists on **1** of those bars. That layer stops being quoted after 09-03; the
print rate of cheap favourite offers rises 0.236 → 0.750.

A supply statistic built on displayed quotes therefore measured mostly ghosts, and produced a
retracted section (§69) claiming the addressable pool had halved. **Any availability or supply
claim must be tape-gated** (require a matching print), and WS-vs-REST *presence* agreement is not
a defence — both feeds agree the ghost is displayed.

## Bug #29 (2026-09-07, rebate-farm): a stop-loss that exits "unpaired" legs must define unpaired AS OF the exit instant

The maker stop-loss ("cut the naked leg N seconds after fill") first measured **+$474/day**. It
exited only legs that were still unpaired **at bar end** — i.e. it knew, at second N, which legs
would never be completed. The causal version (unpaired *as of* the exit instant) is
**−$142.5/day** and never beats doing nothing at any threshold (5s −350, 15s −261, 30s −258,
60s −271, 180s −216 against a −209 baseline), reproducing Aug's `RAND == real` verdict.

Same shape as the earlier dual-ask retraction: **any rule that conditions on a leg's final status
is look-ahead.** Prevention: for every exit rule, write down the exact information set at the exit
timestamp and check that "was it paired?" is answerable from it. If the rule needs the bar's
outcome to decide, it is not a rule.

## Bug #30 (2026-09-07, rebate-farm): a RAND (shuffled-outcome) control is VACUOUS when the quote-price mix is asymmetric

`RAND` — shuffle outcomes within coin×day — is this program's standard control for separating
selection from mechanics. It is only meaningful when the strategy's price mix is symmetric around
0.5. In the mid-bar maker lane it is not: fills have share-weighted **q = 0.3080** against a true
win rate of **0.3012**, so shuffling assigns ≈50% and RAND **must** return
`(0.5 − 0.308)·100 + rebate ≈ +19.46 c/share` by arithmetic. Measured: **+19.81 ± 0.71**.
"RAND +19.8 vs real −0.43, therefore the loss is selection ✓" measures the mean quote price and
nothing else. (Aug's RAND was valid because it ran on a *pair* engine with a symmetric mix.)

**The valid substitute — quoted-vs-filled, which needs no shuffling:**
`E[win − mid]` over ALL quotes = **+0.233 c/share**; over FILLED quotes = **−1.540 c/share**
⇒ dynamic adverse selection **−1.77 c/share**. That is the number, and it is what a selection
control is supposed to isolate.

**Prevention:** before quoting a RAND result, compute what RAND *must* return from the strategy's
mean fill price alone. If that predicts the observed RAND, the control is measuring price mix,
not selection — use quoted-vs-filled or a price-stratified null instead.

## Bug #31 (2026-09-07, sig-cancel): a "cancel trigger" that may fire at the placement snapshot is an ENTRY GATE

Queue-depletion and depth-imbalance cancels scored **+0.080 c/share** on the 1s markout. Forbid
the trigger from firing at the order's *first* snapshot — i.e. make it an actual cancel rather
than a decision not to place — and the effect goes to **−0.014**. 100% of the apparent benefit
was the entry gate, which §5 had already refuted as noise; the cancel mechanism contributed
nothing. **Prevention:** every exit/cancel rule must be run with `minj>=1` alongside `minj=0`,
and the two reported separately. A rule whose effect lives entirely at j=0 is not an exit rule.

**Companion positive control that should be standard here:** a deliberately non-causal trigger
(the *next* 0.5s spot move) scored **+0.404 ± 0.019** on the same harness. Run it whenever a
causal trigger reads null — it separates "no signal" from "no power". In this case it also
supplied the bound that closed the lane: even the clairvoyant cancel left the strategy at
**−0.208 c/share**.

## Bug #32 (2026-09-07, btc5m scan): a pair/arb statistic built from PRINTS is hindsight — and the tell is that it GROWS with latency

Searching the print tape for "moments where both legs were simultaneously takeable at a sum below
break-even" read **+$38,585 / 6 days** on btc. It is entirely artefact, in two layers:

1. **"cheapest opposite-leg print inside the window" is bug #13 again** (min-over-window is
   hindsight). Top hit: a bar where UP moved **0.22 → 0.86 in 400 ms**; the scan buys UP before
   the move and DOWN after it.
2. **Replacing it with the causal "FIRST opposite-leg print at ≥ t+LAT" does not fix it** — still
   +$18,911. Because *a print proves the book WAS at that price at or before the print*, never
   that it is there now, and you cannot retroactively have been that taker. Both legs are then
   read at two different book states.

⭐ **The diagnostic that catches it in one line:** re-run the scan at several latencies.

| LAT | 0.00 | 0.05 | 0.20 |
|---|---|---|---|
| measured "profit" | 18,911 | 23,177 | **39,349** |

**A real arbitrage shrinks with latency. Any edge that grows with latency is measuring path
dispersion, not co-availability.** Make this sweep mandatory for any two-leg construction — it is
cheaper than a control and it is unambiguous.

**The correct form:** read both legs off the **book at ONE instant** (event-exact `(ws,mts)` pairs
of the two token books), then tape-gate for takeability and tape-SIZE-cap (#28). Done that way the
answer on btc is **0 of 1,942,072 states below $1.00 fee-inclusive**, minimum **1.00121**, because
`ua + da ≡ 1 + spread` algebraically (`ua ≡ 1 − db` at 100.0000%, n=1,966,903).

**Companion finding, same session:** a MAKER exit on a market that resolves inside the order's
lifetime is maximally adversely selected — a mint-pair's ask captures **+1.23 c/share** and fills
on **89.8%** of shares, while the 10.2% that never fill are worth **−49.28 c/share**. Non-fill of
an exit ask and total loss of the position are the *same event*. Never model a maker exit's value
from its filled subset. (`docs/strat-btc5m-scan-20260907.md` §2c.)

## Bug #33 (2026-09-07): a per-band gate on a LIVE strategy must be settled from the live fill ledger, never from a replay

**Symptom.** Three independent offline analyses (the lead's, the btc5m scan agent's, and the
rebate evaluator's tape-capped grid) all concluded that btc's losses sit below ask 0.90 and that
`MIN_ASK 0.90` removes them at no cost. **The live fill ledger says the exact opposite:**

| btc, 316 live settled fills, 08-17→09-06 | fills | losses | pnl | ROI |
|---|---|---|---|---|
| below 0.90 | 45 | 6 | **+$75.82** | **+18.89%** |
| 0.90 and up | 271 | 3 | +$44.80 | +1.39% |

The gate would have cost **−$75.82, 63% of all profit**.

**Cause.** Bug #23 in the direction that matters. A displayed sub-0.90 ask fills ~**11%** live
against 22-60% in every replay, so the two populations are not the same trades:
- the LIVE sub-0.90 population is the small subset where the price improvement was **real**;
- the REPLAY sub-0.90 population is dominated by phantom asks that would never have filled.
The sim was not mis-scoring those clips. It was trading a population that does not exist. Note
this is *not* fixed by a tape-size cap (#28) — the capped grid reached the same wrong answer.

**Fix / procedure.** `PF_TE_LIVE_SETTLE` rows in each trader pod's
`logs/logs-training-events.jsonl` (+ rotated `.gz`) carry `avg_px`, `cost`, `payout`, `won`,
`side`, `filled`. Three weeks of it is one read-only `kubectl exec` and it outranks any amount of
offline work on the same question:
```
source ./.dev-env-source          # ABSOLUTE cd first — the context trap
kubectl exec -n every-tick-single <coin>-vacmaker-... -- \
  sh -c 'zcat /app/logs/*.gz; cat /app/logs/logs-training-events.jsonl'
```
**Prevention.** Before proposing ANY price/size/time-band gate on a live strategy, pull the live
fills for that band first. If the live sample is thin, say the question is unresolved — do not
answer it from a replay whose fill rate in that band is 2-6× the live one.

**Gap worth closing.** `req_px` is present on only 11 of 316 rows. Logging the *displayed* ask and
size on every `PF_TE_BET`/`PF_TE_LIVE_SETTLE` would make bug #23 directly measurable per band,
per coin, continuously. One-line recorder change; recommended.

## Bug #34 (2026-09-07, predictor hunt): a mid/book-derived benchmark is only a benchmark when the book is LIVE — gate on `evage`

Hunting for a statistical predictor that beats the btc 5m mid, the first cut read like a jackpot:
`(y − mid)` regressed on the Chainlink-vs-strike displacement scored **t = +4.3**, on
`z_hat = d/(σ√(τ−42))` **t = +7.5**, and inside the user's own 0.40–0.60 band the extreme
sextiles read **±27 pp with |t| ≈ 7–8**. All of it was one artefact.

**Cause.** `mrec` SNAP carries the *bot's* WS-maintained book, and `evage` (seconds since the last
book event) has a fat tail: **p90 = 6.6 s, p99 = 37 s, max 229 s**. On those rows the recorded
`ua/ub` is a **fossil** — the spot has moved 20 bps and the quote has not. Worked example, bar
`ws=1788302700`: `ua/ub` frozen at **0.51/0.50 for all 300 s**, `evage` climbing monotonically to
260 s, **zero prints in the entire bar**, while `d_hat` ran +17 → +34 bps and the bar settled UP.
The "edge" is the distance between a live price feed and a dead quote.

**Decomposition (train, bar-clustered, signed by the model's side):**

| `evage` | rows | bars | median tape in prior 120 s | E[y − mid] |
|---|---|---|---|---|
| **< 1 s** | 9,227 | 918 | 14,522 sh | **+0.22 ± 0.87 pp (t = 0.26)** |
| 1–3 s | 88 | 79 | 10,712 sh | +15.7 ± 4.3 pp |
| 3–10 s | 974 | 498 | **0 sh** | +17.3 ± 2.0 pp |
| 10–30 s | 645 | 338 | **0 sh** | +18.3 ± 2.3 pp |
| > 30 s | 185 | 57 | **0 sh** | +29.2 ± 4.7 pp |

**100 % of the apparent predictive power lives in books with no tape.** On live books the whole
structural feature family is dead: `d_hat` t = −0.18, `z_hat` t = +1.02, `lead_bps` t = −0.33.

**It is not rescuable as a taker either** (bug #23 in its purest form). Fossil rows with
|z_hat| > 2 (16.3 % of bars) show a **+32.91 ± 1.86 c/share** taker edge on the *displayed* ask
(median 160 sh showing, t = +17.7) — but the displayed ask is a fossil too: tape-gated at 5/15/30/
60/120 s only **2.7 / 7.2 / 10.3 / 11.5 / 12.4 %** of those quotes ever see a print at our limit,
and on the ones that do the net is **−5.6 / −2.6 / −5.3 / −7.6 / −9.0 c/share** (total over 6 days:
**−$83 … −$398**). The 11.5 % at 60 s is the same 11 % takeability the fleet measures live.

**Fix.** Every study that compares a model to the market's own price must gate on
`evage <= 1 s` **and** require non-zero tape in a trailing window. Both — `evage` alone still
admits bars that are quiet rather than fossilised.
**Prevention / one-line tell:** if a "mispricing" grows monotonically with book age, you are
measuring your own recorder's staleness, not the market.

## Bug #35 (2026-09-07, predictor hunt): a bar-clustered SE on a MODEL-SELECTED subset understates the error, because the selection is itself estimated

The one surviving predictor config (walk-forward logistic, market logit as an offset) scored
**+6.73 ± 2.61 pp (t = 2.58)** on its selected subset — apparently clearing the +3.1 pp bar. The
clustered SE is correct for a *fixed* subset and wrong for one the model chose.

**The right control** (and note the standard outcome-shuffle is **vacuous** here by bug #30 — it
returns **+27.8 pp** from price mix alone, because shuffling breaks the mid↔outcome link the
selection leans on): **shuffle the FEATURE BLOCK across bars within day, keeping `(y, mid, book)`
paired**, refit the whole walk-forward, and re-select. That null has
**mean −3.32, sd 6.58 pp** — i.e. the honest SE of this statistic is **6.6 pp, 2.5× the clustered
one**. The real +6.73 sits at **z = +1.53, one-sided p = 0.040**, which over the ~46 model
configurations searched is p ≈ 1.0.

**Prevention.** Whenever the reported quantity is a mean over a model-chosen subset, the SE must
come from a null that re-runs the *selection*, not from a cluster-robust SE on the final rows.

## Sample-power note (2026-09-07): what this dataset can and cannot certify, and why more model search backfires

`E[y − mid]` on a binary outcome with mid≈0.5 has SE ≈ **50pp / √n**. So:

| bars | SE | t for a REAL +3.1pp edge (the maker break-even) |
|---|---|---|
| 300 (any selective model's chosen subset) | 2.89pp | **1.07** |
| 1,447 (btc alone, 09-01→09-06) | 1.31pp | **2.36** |
| 9,822 (all 7 coins) | 0.50pp | **6.14** |
| 20,000 | 0.35pp | 8.77 |

**Consequence for model search.** The expected maximum |t| under a *true null* after k
configurations is ≈ √(2·ln k): **k=39 → 2.71**, k=80 → 2.96, k=200 → 3.26. So a 39-config sweep on
1,447 bars needs t > ~3.7 to mean anything, while a genuinely real +3.1pp edge tops out at
**t = 2.36**. **The search bar exceeds the achievable signal: more configurations on the same data
are mathematically self-defeating.**

**Rule.** Before running a model sweep, compute (a) the SE at the sample size you will actually
evaluate on — not the full sample, the *selected subset* — and (b) √(2·ln k) for your config
budget. If (a)-implied t for the target effect is below (b), the sweep cannot produce evidence.
Fix the *data* (pool coins, extend the window, change the target to one with a bigger effect),
never the model count. Declare the config budget in advance and report it.

## Bug #36 (2026-09-07, round-2 predictor hunt): a "windfall" class defined by FILL-vs-DISPLAYED price is a staleness statistic, not an opportunity class — and it cannot be predicted because it has already happened

The live ledger's **sweep** class (filled ≥5% below the displayed ask; 59 fills = 61.7% of all
fleet profit) was commissioned as a prediction target: "which displayed 0.99 asks are stale and
about to collapse in our favour". It is not a forecastable event.

Joining the live fills to the recorder's own 10 Hz book at the order instant (`evage` p50 0.02 s):
**0 of 426 non-sweep fills** had a fresh ask ≤0.95× the bot's `seen_ask`; **13 of 17 sweeps did,
and 17 of 17 had a strictly cheaper fresh ask.** The fresh book also predicts the realised fill
price far better than the bot's own view (MAE 0.51 c vs 0.89 c; r 0.972 vs 0.873). The collapsed
state had existed for a median **0.33 s** before the order was sent.

**So `seen_ask − avg_px` measures the age of the firing process's book, not an opportunity that
arrived while the order was in flight.** Any model built to "predict the sweep" is being asked to
predict a quantity that is already observable at the decision instant from a fresher feed — it
will either look impossibly good (if any feature carries book age) or find nothing.

**Two consequences that generalise.**
1. **Define event classes from the information set of the decision, never from the difference
   between two observations of different ages.** The honest version of this target is
   "does a FRESH ask collapse in the next K s", which has a 4.0% base rate, is genuinely
   predictable (OOS AUC 0.70, feature-shuffle z=+10.7) and is worth **+$3/day ± $3** — i.e. the
   predictable version is the worthless one and the valuable version is not a prediction at all.
2. **Check the concentration before commissioning any model.** Of the sweep class's +$136.15,
   **one fill is 55.9% and five fills are 132.6%** (the other 54 are net negative); the fleet's
   whole current-era profit ex-those-5 is +$40.04, not +$220.53. A 5-event target cannot support a
   model, a resize, or a gate — the sample size to check is the number of events carrying the
   P&L, not the number of rows.

## Bug #37 (2026-09-07, §73 maker hunt): a maker's PnL has THREE terms, and the middle one is the strategy

`half-spread@placement + adverse-selection@fill` is **not** a maker's PnL. The complete identity is

```
win − q  =  (mid@quote − q)      # half-spread, measured when we QUOTE
         +  (mid@fill  − mid@quote)   # DRIFT while we wait — the term that gets dropped
         +  (win − mid@fill)      # adverse selection, measured after we FILL
```

Dropping the middle term credits the half-spread as if the market had stood still between
placement and fill — but the market moving is *the reason the fill happened*. It is not double
counting; it is the whole cost of being a resting order.

Caught in `strat-rebate-farm-20260907` §1, whose components reproduce bit-for-bit
(+0.868/−1.562/+0.254, sum **−0.441** vs its published −0.430 ✔) while the terminal `win − q` +
rebate on the identical 47,038 fills is **−4.624 ± 0.382 c/share** — the drift is **−4.156**. The
same fills sit **+3.30 c ABOVE the mid at the instant they fill** ([maker-resting-order-wall] on
fresh data). The error is 10× in magnitude, sign unchanged, and it made a hopeless lane look
nearly closeable by latency.

**Rules.**
1. **Quote TERMINAL PnL (`win − q`) as the strategy's number.** Markouts are legitimate
   *short-horizon* estimators and are higher-powered — say which one you are quoting, every time.
2. **Print all three terms.** If a decomposition does not sum to terminal, it is incomplete.
3. **A 10× disagreement between two docs measuring "the same thing" is a metric mismatch until
   proven otherwise** — here it reconciled `strat-rebate-farm`'s −0.43 with
   `strat-maker-4060-pooled`'s −7.03 (both were right about different quantities).
4. Anything derived from a *magnitude* (ceilings, $/day, latency break-evens) inherits the error.

## Bug #38 (2026-09-07, §73): a harness that needs BOTH sides of the book silently deletes the cell you are hunting

`tools/mrec/mm.py` skips any epoch unless `ub == ub and ua == ua and ua > ub`. In the last 60
seconds the favourite **has no ask in ~83% of seconds**, so the entire high-price late-window cell
— the one place a 5m maker has a positive sign — was never sampled by any run in this program. It
showed up as a **16-fill** curiosity in the full map, not as a lane.

**Rules.** (a) A **BID** simulation needs a bid; requiring the opposite side is a convenience, not
a constraint — use it only for the no-cross check, and treat a missing ask as "cannot cross".
(b) Whenever a sim reports a cell with implausibly few observations, check the harness's *skip*
conditions before concluding the cell is rare. (c) Log skip counts by reason.
(Same session: `mm.py:load_coin` did not load `evage`, so every `EVMAX` freshness gate written
against it was a no-op. Fixed. **A gate you never tested against a deliberately-failing case is
not a gate** — cf. bug #34.)

## mrec v2 drain reliability (2026-09-07)

The `kubectl exec cat` channel to the k3s cluster runs ~40-100 KB/s under
contention, so btc's ~15-20MB hourly EVENT file can take 5-6 min for a
single transfer. Consequences and the settled configuration
(`every-tick-single/tools/drain_mrec.sh`):
- verification failures in bursts are almost always TRANSPORT, not
  corruption — the pod-side file passes `gzip -t` every time so far;
- the safety rule (delete pod-side only after size+gzip verification)
  means a failure costs nothing but a retry;
- guards now: only files SETTLED ≥90s (hour-rollover gzip race, 09-07),
  6 retries with progressive backoff, parallelism 3 (was 6 — high
  concurrency was itself causing the bursts).
If failures ever persist across cycles for the SAME file, check
`gzip -t` pod-side first; a pod-side-bad file is the only case where data
is genuinely lost (never observed to date).
