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
