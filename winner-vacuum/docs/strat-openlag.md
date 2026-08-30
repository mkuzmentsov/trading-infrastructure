# Bar-open strike displacement (taker) — "openlag". Post-open: DEAD. Pre-open seam: EXISTED mid-Aug, PRICED AWAY by the current market (OOS 08-22→29). Re-check monthly.

Started 2026-08-29 (user mandate: "completely new strategy, 5m crypto only,
don't touch existing bots, gather data as needed"). Session scratchpad:
`scratchpad/openhunt/` (extract_open.py, analyze_open.py, era_pre.py,
robust_pre.py + per-coin `*_open.csv`).

## The idea

The strike of bar N is the Chainlink TWAP over **[ws−62, ws−3]** — it is
LOCKED 3 seconds BEFORE the bar opens and we can reconstruct it to 0.46 bps
(Binance proxy; exactly with recorded `cl`). If spot has drifted away from
the forming strike during that last minute, the bar opens with a genuine
favorite (P(win) ~60-80% at |m0|≥5-8bps) while the books may still quote
~50/50. Two entry points tested: (A) taker at fixed delays AFTER open;
(B) taker on the LAST pre-open (next1) quote, fireable in the [ws−3, ws)
window when the strike is already final.

Dataset: local mrec archive 07-30→08-17, 27,578 labelled bars, 6 coins
(hype/zec excluded — no Binance spot in that era). First-touch discipline,
taker fee 0.07·p(1−p), RES labels.

## ⚠️ ERA TRAP (cost the first pass its headline)

Resolution mechanics changed twice inside the archive (venue changelog):
- **< Aug 7**: settle & strike = POINT Chainlink prices (no TWAP);
- **Aug 7 – Aug 14**: TWAP-30 (strike ≈ mean [ws−32, ws−3]);
- **≥ Aug 14**: TWAP-60 (current regime; 5m switched 30→60 on Aug 14).

A 60s-window strike recon applied to the point era manufactures fake
"displacement" triggers whenever the last minute drifted — those bars are
truly ~50/50, you pay the vig, win% 40-50%. The point-era rows behave as a
built-in negative control and came out properly negative. **Any strike-based
study must split by era; only ≥08-15 rows speak for the live regime.**
(Also: pre-Aug-7 archive data is near-useless for ANY settlement-window
question — the whole TWAP mechanism didn't exist.)

## (A) Post-open taker — DEAD, cleanly

Side = sign(m(δ)) at δ ∈ {2..120}s after open, buy that side's displayed ask.
All eras pooled AND era-split: win% sits 2-5pp BELOW ask+fee in essentially
every (δ × |m|) cell; the book prices the displacement within ~2s of open
(ask already 0.56-0.60 at δ=2 on |m|≥2bps). The three tiny positive cells
(δ10/8-15bps +0.19c; δ30/≥15 +1.25c; δ45/≥15 +0.96c) are non-monotone
small-n noise and pre-haircut (bug #23 fill physics would cut mid-band fills
~7×). Matches [[market-efficiency-proof]]: efficient-minus-spread from the
bar's first seconds. **Do not revisit with more data — the repricing is
mechanical and fast.**

## (B) Pre-open final-seconds taker — the seam. Status: PLAUSIBLE, UNPROVEN

Fire window [ws−3, ws): strike final, spot live, book = pre-open next1 book.
Last next1 quote before open (median 0.1s before open); side = sign(m0).

Era-correct results (|m| buckets, EV c/share after taker fee, displayed ask):

| era | 3-5bps | 5-8 | 8-15 | ≥5bps day-split |
|---|---|---|---|---|
| point (<08-07) — CONTROL | −3.9 | −3.8 | −7.2 | 2/10 pos (correctly dead) |
| TWAP-30 (08-07..13, strike30) | **+2.4** | +1.0 | **+11.5** (n=70) | 5/7 pos |
| TWAP-60 (08-15..17, only ~3d!) | −3.4 | −3.5 | **+14.3** (n=51, 76.5% win) | 2/4 pos |

Firing at ws−3 (pre3, the earliest legal moment) is uniformly ~1c BETTER
than at ws−0.1 — the book starts adjusting in the last seconds; earlier =
staler counterparty.

Known problems (why this is NOT deployable yet):
1. **n is tiny in the only era that matters** (~3 archive days of TWAP-60).
2. **Raw-bps threshold is wrong**: doge dominates triggers (5.7-8.6bps is
   routine doge noise — win ~55% at ask 0.55 ≈ breakeven-minus-vig), while
   5bps on btc/bnb is a real event. The signal must be vol-normalized
   (z = m0/σ_recent) — not yet done.
3. **Event clustering**: the fat wins cluster on multi-coin macro bars
   (e.g. ws1786916400, ws1786962600 — 4-6 coins trigger simultaneously,
   asks 0.58-0.77, all won). §46/§47-style 2-event-fingerprint risk is high;
   cluster-level (per-ws) resampling required before any belief.
4. **Fill physics unknown pre-open**: displayed pre-open asks are resting
   orders (mostly minters); [[taker-side-adverse-selection]] measured 11%
   FAK match at 0.55-0.75 in the LATE window. Pre-open may differ (the
   documented 129k:2.5k pre-open BUY:SELL print ratio proves takers DO get
   filled at scale pre-open) but OUR match rate there is unmeasured. Also
   the venue **50ms crypto taker delay** (changelog 08-17, was 250ms) gives
   makers a pull window against exactly this kind of shot.
5. Displayed depth on trigger bars is real but modest (typ. 20-70sh ≈
   $10-40 at ~0.55).

Why the mechanism is not crazy: [[strat-preopen]] measured pre-open resting
(both directions) as DEAD because "pre-open buyers are informed" — this seam
is simply BEING that informed buyer, with the cleanest possible information
(the locked strike), at the last stale quote. The losers would be the
pre-open mint-ask resters, who are documented to lose ~$195-705/day.

## Validation battery, same session (2026-08-29 ~12:00K) — the seam SURVIVES everything offline

Signal fixed to **z = m0 / σ5m** (σ5m = std of trailing 12 strike-to-strike
log-returns, bps — kills the raw-bps doge-noise problem). Entry = pre3 (last
next1 quote at/before ws−3), side = sign(z), taker fee included. Era-valid
days only (TWAP-30 with strike30 + TWAP-60 with strike60; ~10 days):

| check | result |
|---|---|
| z-monotonicity | t60: \|z\| 0.7-1.2 −1.8c / 1.2-2.0 **+10.0c** (70.4%, n=71) / 2.0-3.5 **+15.4c** (n=14); t30: +5.2c / **+18.9c** — monotone both eras |
| day-split \|z\|≥1.2 | **10/10 era-days positive** (t30 7/7, t60 3/3) |
| per-coin \|z\|≥1.2 | t60: **6/6 positive**; t30: 5/6 (eth n=2 only) |
| cluster (per-ws) bootstrap | 118 triggers / 99 clusters, 72/99 positive; mean EV +14.2c/sh, 95% CI [+4.0, +23.4], P(≤0)=0.0035 |
| ⭐ stratified null (the structure-hunt discipline: draw outcomes from the ALL-bar-sides pool at the same 0.02 ask stratum) | trigger win 65-71% vs pool base 50-53% in every stratum; null mean −7.6, sd 5.4 → **z=+4.53, p<0.0003 (0/4000)** |
| pre-open FILL PHYSICS (next1 `trd` prints, t60 era) | pre-open taker BUY flow is real: ~$28k/day fleet prints inside the last 3s alone; **49.5% of ALL bars** (37.6% of trigger bars, avg 33sh) print at-or-below the ws−3 displayed ask within [ws−3, ws) → the late-window "cheap asks don't fill" wall does NOT apply pre-open |
| capacity sketch | ~12 triggers/day fleet-wide at \|z\|≥1.2; displayed depth 20-70sh at ~0.54-0.62; ≈ $10-30/day at displayed books (before competition response) |

First fully-out-of-sample judge: the cl-era pod extraction (08-22→08-29,
real Chainlink strikes, 7 coins incl hype) — running in-pod
(`/tmp/ocl_<coin>.py → /tmp/<coin>_cl.csv`), disjoint from every number
above. If it confirms: this is the strongest new-lane candidate since the
vacmaker.

## ⭐ THE OOS VERDICT (2026-08-29 ~14:30K) — the seam was REAL and is now PRICED

Judge dataset: 14,056 bars, 08-22→08-29 (8 days), 7 coins, REAL Chainlink
strikes (`cl`/`cl_ts` 1Hz ticks pulled to the local archive — full raw drain
completed, `data/mrec/<coin>/` now also covers 08-22→08-29). Fully disjoint
from every in-sample number above. Scripts: `seam_cl.py`, `seam_cl2.py`
(basis-clean variants), `seam_mid.py`, `seam_early.py` in the session
scratchpad and mirrored to `winner-vacuum/tools/openlag/`.

**What replicated:** the INFORMATION. Trigger win rates hold (70-90%) and beat
the same-ask base rate in every test (stratified nulls z=+2.0…+8.4). The
locked-strike signal is real, permanently.

**What did not:** the PRICE. Pre-open asks on displaced bars now average
0.68-0.76 (archive era: 0.54-0.62) — the pre-open book prices the
displacement before the fire window:
- |z|≥1.2 at ws−3: **−2.4 to −3.1c/sh** (basis-clean variants A/B; archive
  +14c). Stale-book subset (ask≤0.62) nearly extinct: n=7 in 8 days.
- moderate band z∈[0.45,1.2): +1.0c/sh pooled (n=906) — informational, not
  economic; the positive residue concentrates at asks 0.5x (+8c) = exactly
  the band with the 11% live match rate ([[taker-side-adverse-selection]]).
- fire EARLIER: ws−10 mildly positive everywhere (+2.7…+4.1c/sh, p=0.02,
  5/8 days) decaying to ~0 by ws−3; ws−30 dead (partial strike, win 52-56%).
  The leftover is a few cents at ws−10 — under any fill haircut ≈ 0.
- Timing of death: between 08-17 and 08-22 — coincides with the venue's
  crypto taker-delay cut 250ms→50ms (08-17) and/or competitor adaptation.
  The archive proves the exploitable state EXISTED for ≥10 days; it can
  recur (new coin listings, competitor exits, venue changes) → cheap
  standing re-check, not a dead-forever verdict.

**Adjacent findings (same dataset, keep):**
1. ⭐ **T+2 winner detection from relay ticks is 99.98% correct** (2 wrong
   in 12,281) under guards: ≥40 of ~59 settlement ticks arrived AND
   |margin|≥1bps. Unguarded: 99.33%; all big-margin "errors" are relay-hole
   bars (nstrike/nfinal 1-24). Directly validates the live snipe-rest
   min-bps guard; any post-close logic MUST carry a tick-completeness
   check, not just a margin check.
2. **Candidate B (post-close flip-harvest taker) = SMALL, skip.** Winner-ask
   ≤0.90 displays on 2.5% of bars (~44/day fleet) but the print census
   bounds ACTUAL capture at ~$80-170/day for all participants combined
   (taker-buys of the winner <0.90 post-close), vs the $315/day
   sell-into-bid ≥0.99 pool the snipe-rest pilot already targets. The
   displayed-vs-captured gap (~10×) is bug-#23 fill physics again.
3. Pre-open fill physics (archive era) stays true OOS-adjacent: pre-open
   taker flow is real; the constraint is price, not fillability.

## LIVE PROBE (deployed 2026-08-29, user "Proceed")

`src/openlag.py`, releases `<coin>-openlag-every-tick-single` —
**ALL 7 COINS since 08-30 ~14:40K** (btc/eth/sol from 08-30 08:15K; user
"run the same on rest of the coins" added xrp/doge/bnb/hype). hype: no
Binance spot → σ5m from own strike history (~65 min warmup; `sig_src` in
OL_EVAL) and PVC-less (node volume-attach limit) so its halt is not sticky
across restarts. First live cycle (btc 09:49 UTC): attempt-1 ask PULLED
(live adverse-selection datum), attempt-2 filled 5.6sh@0.65, WON +$1.96;
same bar eth skipped at ask 0.76 — the "priced away" verdict live.
NOT an income lane — a measurement probe:
- fire window [ws−10, ws−3] on the NEXT bar's market, side = sign(z),
  z = (latest Chainlink tick / forming strike − 1)·1e4 / σ5m(Binance klines);
  guards: ≥35 of ~59 strike ticks arrived, tick age ≤8s, σ ≥1bps.
- $5 FAK clip (max 2 attempts), ask band [0.30, 0.72], sticky $7/UTC-day halt
  persisted to /app/logs/openlag_halt.json (survives restarts).
- **OL_EVAL fires every bar** (signal snapshot regardless of gate) — builds
  the live calibration dataset; OL_TRIGGER/OL_ORDER give the pre-open FAK
  match rate (the number offline cannot produce); OL_SETTLE + OL_HALT close
  the loop. Judge after ~1 week on: match rate by ask band, EV/clip vs the
  offline −2..+3c band, trigger rate (~4/day/coin expected).

## Standing re-check (the only open action)
`winner-vacuum/tools/openlag/` holds the frozen pipeline:
`extract_cl.py <coin> <mrec_dir> <out.csv>` per coin (needs raw archive
current — pull with the parallel per-coin cat+verify pattern), then
`seam_cl2.py` in the CSV dir. Judge on: |z|≥1.2 pre3 EV/sh, the avgask
column (the tell: ~0.54 = stale book is back, ~0.72 = still priced), and
the stratified-null p. Takes ~10 min. Worth re-running ~monthly or after
any venue mechanics change (fees, taker delay, tick size, new coins).
Deployment bar if it reopens: the archive-era battery of this file §
"Validation battery" + a $5-clip live probe for pre-open FAK match rate.

## Venue docs sweep, same session (2026-08-29)
- **50ms crypto taker delay** (Aug 17 changelog, down from 250ms) — a
  venue-side maker-protection delay on crypto markets; part of the bug-#23
  ask-pulling mechanism. First time this knob is in our docs.
- **Combos** (parlays) exist as an RFQ system (400ms maker quote window,
  optional last-look at $2.5k+ notional, Exchange v3 signed quotes, REST
  `/v1/maker/quotes` + WS). Eligibility of 5m crypto legs undocumented;
  relationship-gated. Parked — note that being a combo MAKER on correlated
  crypto legs would be a correlation-pricing game if crypto combos ever
  open up.
- Perps launched (separate product; out of scope per user's 5m-only rule).
