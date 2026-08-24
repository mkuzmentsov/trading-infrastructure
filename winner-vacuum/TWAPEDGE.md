# twapedge — the TWAP settlement edge: rule, evidence, backtests, verdicts

Written 2026-08-08, after the first 38h of the new settlement regime.
Data: mrec 100ms recorders (6 coins, 30 Jul → 8 Aug 12:00 UTC), gamma
settlement references for every bar since 5 Aug (6,148 markets), the twapedge
fleet's own live RTDS estimates (3,499 audited bars), and 120d × 6 coins of
Binance 1s klines. Every headline number is scored against the exact
`priceToBeat`/`finalPrice` the venue published for that bar.

## 1. The regime change, solved exactly

On 2026-08-07 00:00 UTC these markets stopped settling on a point sample and
started settling on the Chainlink 30-second TWAP. Three facts, each proven on
the fleet's audit records (PF_TE_VERIFY vs gamma):

1. **The end reference is the TWAP tick stamped at T, covering [T−32, T−3].**
   Our reconstruction of that window from the 1Hz RTDS point feed matches the
   published `finalPrice` to a median **0.0019 bps** (the [T−29, T] window:
   0.077; the point tick: 0.40). 40× separation — not ambiguous.
2. **Chaining held on 2,237/2,237 bars**: `finalPrice[N] == priceToBeat[N+1]`
   exactly. Both ends of every bar are the same TWAP series, which means the
   strike is **fully determined 3 seconds before the bar opens** and is
   published verbatim on the `crypto_prices_twap_thirty` topic as the tick
   stamped at the bar-open second.
3. **The outcome is therefore fully determined at T−3**, and our real-time
   reconstruction of it (live fleet logs, corrected to the true strike) called
   the settled outcome at T−4.5s:

   | \|est\| bps | accuracy | n |
   |---|---|---|
   | 0–0.25 | 93.0% | 128 |
   | 0.25–0.5 | 99.0% | 103 |
   | 0.5–1 | 99.1% | 212 |
   | 1–2 | 99.7% | 354 |
   | 2+ | 99.9% | 1,607 |

   The residual misses are true knife-edges (`est` ≈ 0.00, settled move
   0.00–0.35 bps). Pre-switch, the *same* estimator scored 48.8% on ties and
   92% at 2–5bps against the point rule — the regime contrast is the proof
   the accuracy comes from the rule, not from fitting.

Feed facts that matter for implementation: subscribe **without** a `filters`
field (filters silently kill the stream); every tick carries the value in two
scales (normalise before mixing); relay latency p50 ≈ 1.6s; the strike tick
for bar ws must be the tick stamped exactly at ws (a neighbour is a different
reference — a stale-tick strike flipped a 0.13 bps doge bar on 6 Aug).

## 2. The edge that survives: buy the implied winner into a stale book

The book prices off the last price; settlement is the TWAP. In the final
seconds those disagree constantly at sub-bp scale, and only a
settlement-exact reconstruction knows which side is right.

**Backtest** (post-switch mrec books × live corrected RTDS estimates, one
entry at T−5s, buy the implied winner at its ask, `sh = min(50, ask_size)`,
taker fee 0.07·p(1−p)):

| gate | trades/1.54d | win | PnL | per day |
|---|---|---|---|---|
| ask ≤ 0.97, all est | 153 | 90.2% | +$470 | **+$305** |
| ask ≤ 0.97, \|est\| ≥ 0.25 | 76 | 92.1% | +$335 | +$218 |
| ask ≤ 0.90, all est | 80 | 82.5% | +$387 | +$252 |

Losses are exclusively `est ≈ 0.00` knife-edges. Per-coin: all six positive
(btc +$111, eth +$154, xrp +$72, doge +$67, bnb +$35, sol +$31).

**Decay is real and quantified.** The windfall was day-1: the ≥0.25bps
component collapsed from 52 trades/+$268 in the first 6h to ~5/6h after —
the book learned the big disagreements in ~24h. What has **not** decayed is
the knife-edge component (est < 0.25): steady 11–20 trades/6h at 88% win
across all seven buckets. Steady-state total after the first 6h:
**≈ +$130/day** fleet-wide at 50-share caps (~$4k/day notional).

A kline-signal variant entering earlier (any k ≤ 30, |est| ≥ 3bps, ask ≤
0.97) adds 100%-win trades (142/142 over the window, +$209/day) but is even
more front-loaded — the supply of ≤0.90 asks on already-determined bars went
11 → 0 per 6h across the window. Treat early entries as opportunistic
garnish, not the base.

Capture realism: median ask size at qualifying moments is 15–80 shares, and
the levels are not being raced away — 88% of ≤0.97 asks visible at T−5 are
still there (same or better, with size) at T−4, 87% at T−2. A taker with the
~1.6s relay plus FAST_EXEC comfortably reaches them; assume partial capture
scales the PnL roughly linearly. The moat is the exact reconstruction:
anyone pricing off Binance carries ~0.5bps of cross-venue noise (accuracy on
ties: 71% vs our 93–99%).

The exact v2 gate (ask ≤ 0.97 at |est| ≥ 0.10, ties only ≤ 0.45) replayed on
the steady-state window: 57 trades/31h, 88% win, **+$122/day**, spread flat
across UTC hours (20 of 24 positive) — no session dependence.

## 2b. Adversarial verification (independent reimplementation, 2026-08-08)

A separate agent rebuilt the whole pipeline from the raw gz archives and event
logs with its own code. Verdict: **A, B, D confirmed; no artifact found.**
- Accuracy: 99.74% at |est| ≥ 0.25 bps (2339/2345), 93.1% below.
- Trade: 153 trades / +$469.82 (+$306.8/day) — matches to <1%; excl. first 6h
  +$131.9/day. Robust to stricter decision timing (tl ≤ 4.4/4.0/3.0 all +).
- No look-ahead (decision snaps tl med 4.96, none post-close), no duplicate
  bars, labels perfect (settle2 vs recorder RES: 0/4,392 disagreements),
  traded asks persist +300ms in 143/153 cases.
- The strike correction is what makes it work: uncorrected, sign accuracy is
  only 95.4% at ≥0.25 bps (the logged v1 bot never traded this signal).
- Pre-switch null: 72.8% at |est|<1 vs 97.3% post — the edge is causal.
- **Decay, sharper than §2's estimate:** PnL per 6h since the switch:
  +300, +69, +17, +56, −5, +31, +2. The last ~12h run-rate is **~$30–55/day**,
  89% of bars now show an EMPTY winner-ask at T−5 (sellers adapted), and the
  post-6h profit is concentrated (top-5 trades = 78% of that segment's net;
  median trade +$1.40). The durable residual = the 0.90–0.97 ask sliver plus
  rare mispriced ties.

## 3. What the regime change does NOT give

- **Mint-salvage 2.0** (mint the pair, rest an ask on the now-known loser
  from T−3 into the persistent $7.8k/day post-close loser-buy flow):
  REFUTED. Over 1.5d: ~$220 revenue vs ~$200 of mislocks. Selling at 1–50c
  against a $1 loss per wrong bar needs >99.9% accuracy *conditional on
  filling*, and fills adversely select the ambiguous bars. Same coupling that
  killed every resting-loser variant before; determinism does not fix it.
- **Post-close pots are unchanged** (loser-buy $7,786/day vs $8,769 pre;
  snipe $3,283 vs $3,201) but remain what they were: the loser-buy flow
  prints at high prices on near-ties (wrong-side buyers — reachable only by
  selling exactly where our error concentrates), and the snipe pot is a 1–2
  event/week lottery.
- **1h/1d series**: post-close flow ~$150 per 2 days on btc-1h. Not a market.

## 4. Live setup (paper) as of 2026-08-08 ~14:10 UTC

`twapedge` gate v2, six coins, paper: at T−4.5s buy the implied winner when
ask ≤ 0.97 and |est| ≥ 0.10bps, or ask ≤ 0.45 on ties; 50 shares; strike =
TWAP tick at ws read off the feed. The settle log scores every bar against
point/H1/H2 and the verify loop audits our references against gamma ~20min
later — drift shows up as PF_TE_VERIFY ok=false, loudly.

Expected while the edge lasts: ~90–95% hit, ~$130–300/day paper. Go-live
would need: FAST_EXEC wiring for the T−5 taker buy, the fill-race measured
(paper fills assume we take the whole visible ask), and a decision on size.

## 5. Watch list

1. Whether settlement reads the tick at T (window [T−32,T−3]) — current
   evidence — or T+3. Both trailing; the estimator differs only in the tail.
   PF_TE_SETTLE's h1/h2 scorecard resolves it continuously.
2. Book adaptation speed: the day-1 harvest is gone; if the knife-edge
   component also decays below ~$50/day, the trade stops being worth the
   infrastructure.
3. Polymarket changing the rule again (they moved 5m markets once; the
   15m/4h series use 60s windows — untested by us).

## 6. 2026-08-15/16 — twapedge became the vacmaker fleet engine (addendum)

The paper bot above grew into the live 6-coin vacmaker program. Deltas vs
the doc above (full ops history: docs/vacmaker-offline-notes.md §7-15,
strategy: VACMAKER.md):
- **Settlement**: ALL coins now TWAP-60 → `pmTeTwapWindow=60`
  (crypto_prices_twap_sixty, H1 window [T−62,T−3]).
- **Env added since**: PM_TE_MIN_COVERAGE (floor ≈ (62−eval_tl)/59 − slack;
  the 0.8 default silently blocks any early-eval deploy), PM_TE_SNIPE_*,
  PM_TE_LOCK_*, PM_TE_MAKER_REST_PX (default 0 = OFF, taker-only),
  PM_TE_LIVE_* caps, and 08-16: **PM_TE_LIVE_RETRY_S (3.0) /
  PM_TE_LIVE_RETRY_GAP_S (0.3)** — retry-FAK after a killed order,
  re-firing only with a validated in-band ask AND the estimate still
  same-side ≥ thresh ≥ coverage floor. PF_TE_LIVE_ORDER carries attempt=N;
  PF_TE_LIVE_RETRY_STOP logs signal-decay aborts.
- **prewarm_loop** (08-16): pays each new market's neg-risk REST lookup at
  WS market-switch (~35-39ms, PF_TE_PREWARM) — it used to run INSIDE
  create_order on every live order (~300ms of the 344-657ms sign+post,
  since every 5m bar brings fresh tokens). warm_loop (session keepalive)
  already existed; the tick-size cache was already WS-patched at sign.
- **Live-loss taxonomy** (5 losses to 08-16 noon): whisper-entry (eth×3,
  sub-0.5bps reads — gate-fixable) vs decay-to-tie (hype, bnb — entry
  ≥0.8bps decayed to |final|<0.05bps, tie against us; NOT gate-fixable).
  All verified exact vs gamma (PF_TE_VERIFY strike/close err 0.0bps).
- **Sim-freshness caveat**: paper fills trust the last WS top-of-book; a
  starved feed manufactures phantom wins (backtesting.md ledger #15,
  eth 08-15 16:29-17:27 UTC rows are fiction).
