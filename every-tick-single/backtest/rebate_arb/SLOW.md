# Two-sided arb on the slow bars — and the btc reversal of §4g (2026-08-02)

Data: the hourly/daily recorders deployed 31 Jul for exactly this question
(`btc-mrec1h`, `btc-mrec1d`, 100ms schema). **51 resolved hourly bars**
(31 Jul 05:00 → 2 Aug 08:00) and 2 resolved daily bars, plus the existing
4-day 5m cache for cross-checks. Winners fetched from gamma (`slow_extract.py`)
because the archives contain zero RES rows — hourly/daily markets carry
`customLiveness=600`, so gamma flips `closed` ~10-11 min after close, exactly
when multi_recorder's 600s post-close give-up had already dropped the market.
Recorder patched (600→1800s for slow bars); backtests don't depend on it.

## 1. The slow-market hypothesis is dead on arrival — the book is self-similar

§4e deferred the maker-maker mechanism to "slower markets that sit near 50c".
They do not exist in this series:

| | 5m (measured 4d) | 1h (51 bars) | 1d (2 bars) |
|---|---|---|---|
| median first-half range of ub | 0.42 | **0.42** | 0.32 |
| median time with ub in [.45,.55] | — | 13% | 0% |
| median 0.50-crossings | — | 5 | 0 |

The identical 0.42 is not a coincidence: an at-the-money binary's book path
depends on |move|/σ√t, which is scale-free. Stretching the bar stretches the
clock, not the shape. There is no timescale on which the book "oscillates
quietly near 50c" — the regime the bid-side farm needs is absent by
construction, on every bar length.

Confirmed by simulation — every bid-side config is WORSE on 1h than on 5m
(the hour gives price room to run through one bid and away from the other;
61-82% of entered bars end legged):

| config (1h btc, 100sh) | net/bar | t |
|---|---|---|
| seqpair 0.49/0.49 hid=50 complete@1s | −$13.09 | −6.1 |
| seqpair 0.45/0.45 hid=0 complete@1s | −$2.96 | −1.8 |
| seqmaker v2 p1=.48 rescue@fill+60s hid=50 | −$16.95 | −8.5 |
| any of the above, ride to resolution | −$24 to −$32 | −7 to −9 |

Rebate earned in all of these: ~$0.50/bar against $3-30/bar of losses.

Per-print realized spread agrees: hourly mid-band BID fills are −2.3c/sh at
resolution (front-of-queue optimistic), same sign as 5m. Hourly flow is not
less informed — there is just less of it per second.

**Pools, print-exact** (0.07 fee, 20% rebate): hourly btc series ≈ **$970/day**
whole-market rebate pool (med $202/bar taker fees) — 9× the daily series
($245/day over 2 bars, vs $106-117 estimated earlier), and the 5m btc series
dwarfs both at **~$27k/day** (med $438/bar). Fees concentrate at mid prices
(41%) and in the first quarter of the bar (40%). Taker flow is 85-89% BUYS on
every series — the bid side farms the 11% minority; asks face the 89%.

## 2. The ask side: §4g's "worst config" verdict was a Simpson artifact

§4g ran mint+dual-ask pooled over six coins and reported −$22/bar t=−65,
"worst of all seven configs". Re-run per-coin with a delay-based neutraliser
(dump the stuck complement ~1s after the single fill — msell.py only had an
absolute-time rescue), 0.55/0.55, hid=200, 4 days:

| coin (5m) | both-fill | net/bar | t |
|---|---|---|---|
| **btc** | 67% | **+$3.99** | **+11.0** |
| eth | 50% | −$3.93 | −7.5 |
| sol | 26% | −$20.36 | −32.9 |
| xrp | 8% | −$33.11 | −61.4 |
| bnb, doge | 2% | −$20 to −$25 | −14 to −28 |

The pooled −42σ buried a +11σ btc-only result. The variable is per-bar
volatility relative to the book: btc is the only coin whose bar is quiet
enough that the book SWINGS through both asks (sell U on the up-swing, sell D
on the down-swing → collect aU+aD > $1 on a $1 mint, outcome-immune) instead
of converging one way. On the leg that never pairs, complementarity caps the
damage: the stuck side dumps at ≈ 1 − ask − drift, so a legged bar costs cents
where the bid-side single cost fifty.

**The same config is positive on the independent hourly dataset** (different
recorder, different week, 51 bars): 0.55/0.55 hid=200 → +$3.16/bar t=+2.4;
entered pre-open +$4.20/bar t=+3.5; 0.65/0.65 +$5.25/bar t=+2.2.

### Stress battery (all on the btc cuts)

- hidden queue: 5m 0.65 survives **hid=1000** (+$4.12/bar t=+5.7); dies ≥2000.
  0.55 dies at 1000. 1h 0.55 breakeven ≈ hid 500. Deeper ask = more robust
  (bigger lock absorbs more queue cost).
- dump slippage 10c through the bid: still +$4.76/bar t=+5.7 (5m 0.65 hid=200)
  — the maker-098 "live salvage 2× worse" haircut is far inside this.
- reaction delay 0.5s → 30s: unchanged. **Not a latency edge.**
- margin sweep: net RISES with ask distance to 0.65 (5m: +$10.05/bar t=+15;
  46% of btc 5m bars print both tokens ≥0.65 — the endgame flip-flop).
- endgame cutoff HURTS (final-seconds flow completes pairs — don't cut).
- entry: bar-open or pre-open only; mid-bar entry is −4 to −10σ (both-fill
  needs the whole bar's swings).
- integrity: mirror-print coincidence 0.5-3.7% (no double-printed matches —
  also implied by the 89/11 buy skew); print tape = 0.93-1.00× official volsh;
  top-3 bars = 1% (5m) / 20% (1h) of total; every recorded day positive on
  both series; med bar = the +$10.69 full-pair cap.
- fill sources at ≥0.55: 12% at-ask, ~35% within 30c, ~50% gap-sweeps ≥30c
  above — sweeps clear the whole level, which is where queue position matters
  least; the hid parameter prices exactly this.

## 3. Where it stands

Sim says: the one riskless-shaped configuration in two studies of this family
— and it sits on the ONE quantity this dataset cannot provide (§4): the real
resting queue at mid-book levels. §4 calibrated ~3,000sh hidden at the 0.99
magnet; at 3,000 everything here dies. At ≤1,000 it prints ~$4-10/bar on 5m
btc. The sim cannot pick a point inside that range — a live probe can, at
measurement cost: **rest ~20sh dual asks (0.55 or 0.65) on btc 5m + btc 1h
for a day, count fills vs sim-predicted** — the identical live-vs-sim test
that exposed the vacuum's 9.8×. Worst legged bar at 20sh ≈ −$6-9. If the
trailing-ladder farms (the live wallets already monetizing this flow) fill
the queue, the probe under-fills and the answer was cheap.

Capacity honesty: sim's $2-2.9k/day at 100sh does NOT extrapolate — marginal
size climbs the queue curve. The btc 5m fee pool ($137k/day gross, $27k/day
rebate) says the flow exists; the seat, not the flow, is the constraint.

Daily series: 2 bars, both trended (0 mid-crossings, 0% time near mid) — no
sim is meaningful; recorder now accrues RES-complete data; revisit at n≥14.

---

# RETRACTION (same day, hours later) — §2-3 were a LOOK-AHEAD artifact

Re-deriving the mechanics to describe them exposed the flaw: `slow_deep.py`
dumps the **eventual end-of-bar residual** at *first-fill + 1s* — a moment
when a real bot cannot know what the residual will be (the complement's fills
come minutes later, if ever). The sim was implicitly running a perfect
trend/chop classifier: exit instantly (at the −1c-to−5c price that exists
only right after the fill) in exactly the bars where the pair won't complete,
hold in exactly the bars where it will.

`slow_exec.py` replays the same fills through a 1Hz state machine with only
implementable rules — imbalance timer X (dump stuck at bid on expiry, reset
if paired back), stop-K on the stuck side's bid, combinations, ride:

| 5m btc, hid=200, 100sh | fullpair | net/bar | t |
|---|---|---|---|
| 0.55 ride | 67% | −$7.39 | −8.1 |
| 0.55 timer 120s | 52% | −$5.98 | −8.5 |
| 0.55 stop 0.40 | 15% | −$5.30 | −18.0 |
| 0.65 ride | 45% | −$4.88 | −4.2 |
| 0.65 timer 120s | 25% | −$4.22 | −4.9 |
| 0.65 stop 0.40 (≈dump-on-fill) | 0% | −$4.07 | −25.1 |
| best 1h config (0.65 stop 0.30) | 4% | −$2.72 | −2.4 |
| 0.65 stop 0.25, hid=0 | 20% | −$3.27 | −5.3 |

Every implementable point on both datasets is negative. The structure is the
familiar coupling: **to keep the both-fill option you must hold the stuck
side through its collapse, and the collapse costs more than the lock pays.**
Fast exits forfeit the pairs (timer-10s keeps 4%), slow exits eat the
collapse; the ~$11/bar gap between clairvoyant and honest is the value of
knowing the future. No entry- or fill-time observable separates pairing bars
from stuck bars (§2's finding, again).

**§4g's original pooled verdict stands. The btc "reversal" is retracted.**
The live probe proposed above is WITHDRAWN — there is nothing to probe; the
queue question is moot when the hid=0 case already loses. What §1 established
(book self-similarity, pool sizes, 89% buy-skew, hourly bid-side −3 to −9σ)
is unaffected: those are direct measurements, not fill sims.

Meta-lesson for every future maker sim in this repo: **any rule that prices
an exit using quantities finalized later in the bar is look-ahead**, however
innocent it looks. The give-away here: "delay sensitivity 0.5s→30s ≈
unchanged" — a real exit's cost is dominated by WHEN you decide, so
insensitivity to the delay was the smell that the decision itself was
clairvoyant.

---

# Addendum (2026-08-02, later) — mint 50/50 + resting 99c asks (user variant)

`snipe99.py` / `snipe99b.py`. The structure is different from the farm: an
unsold minted pair redeems at $1.00, so the baseline is exactly zero and the
worst case is bounded at −1c/share/bar. Branches per 100sh: winner's 99c ask
fills → −$1 (96% of bars print a taker BUY ≥0.99 on the winner); the
**loser** prints a taker BUY ≥0.99 in **1.5% of bars** (71/4,860 — knife-edge
flips) → +$99 jackpot; optional 5c leg on the complement after a 99c fill.

Findings, in kill order:

1. **The user rule as stated ("when one fills at 99, delete other, place 5c")
   has a partial-fill disaster**: an 8-share false spike on the loser triggers
   dumping the full 100-share complement — the actual WINNER — at 5c. Worst
   bars −$84 to −$92. Sizing the 5c leg to the filled quantity fixes it, but
   the leg is still EV-negative (−$0.11 to −$0.14/bar, t to −3.6): it caps
   every jackpot at +4c (a 5c ask on a secretly-winning complement always
   fills) and collects +5c only on already-dead losers.
2. **Ride (no 5c leg) is the best shape and it is a fair lottery**: at zero
   queue +$0.09/bar (t=+0.68), at hid=100 −$0.06/bar, at hid=300 +$0.02/bar —
   zero ± noise everywhere. The tails studies said cheap tails are
   fairly/over-priced; this is the same fact mirrored to the 99c level.
3. **Timing does not separate drag from jackpot**: winner's first ≥0.99 print
   median tl=32s, jackpot prints median tl=29s, 80% in the final 20% of the
   bar. Both are the same endgame knife-edge event — in the jackpot case the
   certainty then flips. Every cancel-at-tl cuts jackpots proportionally with
   drag (cancel@45s: −$0.02/bar).
4. **The measured 0.99-level ask depth ends the queue debate**: when 0.99 is
   best ask on 5m btc, visible size is **median 4,265sh, p25 2,586** —
   matching §4's live vacuum calibration (~3,000). The level is the crowd's
   profit-taking/ladder magnet; open-placement priority does not beat a
   4,000-share standing wall. 1h: median 288sh but ZERO jackpots in 51 bars
   (an hourly bar's loser never touches 0.99) → pure drag, t=−20.

Verdict: bounded-loss, zero-EV lottery behind a 4,000-share queue. Nothing to
deploy; closes the last untested corner of the 2-side arb family. Selling at
0.99 is the counterparty side of our own vacuum — the tape keeps saying the
PAID side of that level is the buyer after close, not the seller before it.

## Round 3 — the conditional flip (full-fill + lead/time gates), user 2026-08-02

Proposal: flip the complement to a 5c ask only when the 99c leg sold
COMPLETELY, and/or gate the flip on time-left and the spot's distance from
the bar open. `snipe99c.py` + a parallel 1Hz lead cache (`lead_extract.py`).

1. **Full-fill condition**: fixes the disaster (worst bar −$1.00 everywhere
   now) — but it is itself adversely selected. Jackpot events are HALF the
   size of drag events (≥0.99 BUY volume med 76sh vs 215sh x6; 1,458 vs
   3,978 btc), so requiring a complete 100sh fill preferentially keeps the
   −1c branch and drops the +99c branch.
2. **The lead gate does not exist in the data.** Lead toward the printing
   token at the first ≥0.99 print: jackpots med +5.4bps (p25-p75 3.0-8.6),
   true winners med +7.5bps (3.7-12.8) — nearly the same distribution. At
   tl≈30s a few-bps lead is what prices 0.99 in both cases; whether it holds
   the last 30 seconds is the coin flip the 0.99 quote already encodes.
   Gate table: Y=6bps flips 59% of drag but wrongly caps 26/71 jackpots
   (−$95 each); Y=25bps caps ~none but flips 2-4% of drag → collects ~no 5c
   → equals ride. Time gates: same event timing (med tl 29s vs 32s), no
   separation (round 2).
3. Sim ladder at every queue depth: flip-always −$0.32 to −$0.37/bar
   (t −4 to −13) < gated (monotone toward zero as Y grows) < **ride ≈ $0**.
   The best member of the family is "never flip" — the fair lottery again.
   1h: zero jackpots exist; every variant −3 to −20σ.

Program-level conclusion, three rounds in: every observable at decision time
(price, time-left, lead, fill size, book state) is already inside the 0.99
price. The only lever that has EVER separated anything here is queue priority
in a window where information is dead — which is the vacuum, already built.
