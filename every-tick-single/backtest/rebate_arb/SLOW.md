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
