# Bar-open strike displacement (taker) — "openlag". Post-open: DEAD. Pre-open final-seconds: OPEN SEAM (data-starved).

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

## Next steps (in order)
1. **Data**: cl-era pod pull (08-22→08-29, all 7 coins incl hype, real
   `cl`/`tw` fields) — running 2026-08-29; archive keeps growing daily,
   revisit at ≥10 TWAP-60 days.
2. Re-run (B) on cl-truth strikes with vol-normalized z, cluster-dedupe
   (per-ws), stratified permutation null, per-coin split.
3. If it survives: measure pre-open fill physics BEFORE sizing — a $5-8
   probe lane (needs user sign-off) or passive measurement of pre-open
   prints vs displayed asks in mrec (`trd` on next1 rows — data exists).
4. Only then think about an executor (FAST_EXEC presign; fire at ws−3..ws−1
   on z-gate; strike from live rtds TWAP-60 stream like vacmaker).

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
