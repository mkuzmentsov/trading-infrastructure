# poolfarm-1h — 1-hour neutral pairs. VERDICT: WORKS SMALL (live-proven). OFF by user choice.

Code: `src/poolfarm.py` with `BAR_SECONDS=3600`. Yaml
`chart/bots/btc_poolfarm1h.yaml`. LIVE 2026-08-13 01:26–13:37 Kyiv.

## Thesis (user's insight, validated)
A 1h bar oscillates enough for BOTH 50sh legs to fill below their respective
mids → a neutral pair; the pair-cost ceiling locks pair <0.985 → guaranteed
profit at settlement regardless of direction. Adverse selection stops
mattering once neutral. Settlement (Binance 1H candle close≥open) IS the
exit; no intra-bar bounce needed.

## Backtest (offline, real recordings)
Extractor `scratchpad kl/ext1h.py` over ~7d mrec1h raw → `ex/btc-1h.pkl`
(88 bars, 91%-UP trend week = conservative for completion). Sim
`kl/pf_bt_dur.py`: completion 4% (5m) → **84%** (1h); pair cost median 0.892,
100% <1.00; one-sided 42%→15%. Fair-zone band [0.35,0.65] chosen (win-rate at
extreme mids is base-rate artifact).

## Live results (btc, $112-148 bankroll, edge 1.5¢, quit 60s, warmup 30s)
- **7/7 bars formed clean 50/50 pairs at 0.97–0.98, +$1.00/±0.01 each.**
  Completion 100% vs backtest 84%.
- Night 1 (01:26–05:0x): 6 pairs +$5.99, zero losing bars, then the
  **over-accumulation bug** (see 5m doc #bugs): 150 DOWN/50 UP → −$53 bar +
  collateral drain + "not enough balance" storm. Fixed with the
  unconditional inventory per-side cap; re-validated live (max/side 50.0).
- Session 2 (11:18–13:37): 1 more clean pair; 2 solo legs killed mid-flight
  when user ordered the stop (−$25 net).

## Economics / limits
- ~+$1/bar × 24 bars/day ≈ $15-20/day gross at 50sh, minus occasional solo
  bars. Capital: one pair ≈ $48 locked ~1h (+resolve lag ~15min; MAX_INV
  gate then blocks the next bar's start — throughput cost).
- **1h has NO maker rebate** (makerRebatesFeeShareBps=None, verified) and
  reward presence ≈ 0 for us (quotes fill within minutes then nothing rests).
  So income = the pair edge only.
- Batch variant (PM_MM_BATCH_SH) backtested on 1h: batch 10 cuts worst bar
  −$29→−$10 but matched volume 16→9 sh/bar; batch 50 (one-shot) was the live
  config.
- MERGE upgrade (available via adapter, untested live in poolfarm): matched
  pair → mergePositions → $1 back instantly instead of waiting settlement;
  same PnL, ~10-30× capital cycle rate, kills the MAX_INV dead-time. Worth
  building if this strategy is revived.

## Open items if revived
On-chain inventory reconcile at startup (mid-bar restarts unsafe), merge
integration, multi-coin (eth 1h exists), and honest re-check of completion
in a choppier week (the 84% came from a trend week — real rate could be
HIGHER in chop).

## RELAUNCH 2026-08-20 — 1h batched pair engine, btc + eth LIVE

Relaunched after the 5m openmm pilot lost 32% ([strat-openmm-5m](strat-openmm-5m.md)).
User's framing: "1h maker with batched small buys, as neutral as possible."

**Deployed `poolfarm.py` unchanged in strategy — NOT a new bot.** It already IS
this design (`PM_MM_BATCH_SH` is the batched-buys throttle) and it carries every
safety mechanism the from-scratch 5m bot had to learn by losing money. Writing a
new bot produced 6 live bugs in 2 days; reusing this produced 0 strategy bugs.
Configs: `chart/bots/{btc,eth}_poolfarm1h.yaml`, `BAR_SECONDS=3600`,
SIZE 10/side, BATCH_SH 5, PAIR_CEIL 0.985, MID band .12-.88, QUIT_TL 60,
MAX_INV_SH 30, $8/day halt. Account 0xd632c1e1… (NOT the vacmaker fleet's).

### Why 1h and not 5m/15m/4h
- **The 5m killer was the UNPAIRED leg** (53% of shares). Pair completion is
  mechanical in bar length: 5m 63% → 15m 72% → 1h 84%. Batching caps the
  unhedged residual on top.
- **4h rejected for now**: only ~14 bars of data exist (recorders since 08-17).
  Better in theory, untestable in practice — deploying it would repeat the
  mistake that cost 32%.
- **15m measured**: aggregate maker terrain is the BEST of the three
  (net +0.259 c/sh vs 5m −0.010 and 1h −0.254), and the "underdog .15-.30" cell
  looks like +2.09 c/sh — but it **dies under a queue model (+0.17, t=+0.12,
  RAND +22.46 ⇒ −22.3 c/sh adverse selection)**. Third field cell to die that
  way. The 1h aggregate terrain is NEGATIVE and that is fine: **a pair bought
  below par pays 1−a−b regardless of who wins**; the terrain only taxes the
  residual leg.

### 1h market facts (differ from 5m — verified live)
- Settles on **Binance 1h candles**, not the Chainlink TWAP ⇒ our spot feed is
  the exact settlement source, not a biased proxy.
- Slugs are ET name-based (`bitcoin-up-or-down-august-20-2026-5pm-et`);
  `window_slug`/`grid_window_start` already handle 3600.
- Resolution via **UMA, 600s liveness** ⇒ capital locks past the bar.
- **No funded liquidity-reward pool** on 1h (`rewards/markets` count=0 — the
  $1M program is 5m/15m/4h). The maker REBATE does apply (rebateRate 0.2).
- **Only btc and eth are viable.** Measured 1h books: btc $16.5k/day vol,
  eth $2.1k, then xrp $695, sol $229, doge $45, bnb $13 with 3-11c spreads.
  A pair cannot complete at $13-695/day and an unpaired leg cannot be exited.
  **Do not deploy sol/xrp/doge/bnb.**

### First 8 bars (live)
100% pair completion (8/8), mean pair sum 0.980-0.985, **unpaired 20% of shares
vs 53% at 5m** — the thesis delivering. Net worth $114.69 → $125.39 (+$10.70),
0 halts, 0 crashes. ⚠️ Most of the early gain was a LUCKY unhedged win (below),
not the pair engine; the engine itself contributed ~$1.50 over the first 4 bars.

### ⭐ NEW: venue-truth reconcile loop (added to poolfarm.py)
The hard per-side cap is `sh = min(BATCH_SH, SIZE − mine)` — arithmetically
correct, but `mine` comes from `self.inv`, which only updates via order polling.
**Any fill we fail to detect leaves inv stale and silently disarms the cap.**
Live 2026-08-20 14:00 ET: 4 down fills (19 shares) during a fast dump went
undetected → bot bought 29 vs 10 against a SIZE=10 cap → a 19-share unhedged
directional bet (which happened to win, +$8.80 — pure luck).

`reconcile_loop` polls the venue and raises `inv` toward truth. It only ever
RAISES, so it can only make the cap STRICTER — fail-safe by construction.
**Three bugs in that one loop, all found by testing rather than waiting:**
1. **Inert query.** `/positions` caps at 100 rows and this vault is saturated
   by 100+ ancient worthless rows (sz=248 @ 2c) ⇒ our live rows never appeared;
   it logged zero errors and protected nothing. **Fix: `redeemable=false`**
   (4 rows). Same endpoint trap that produced a false "−$28.50" alarm the day
   before. On first correct run it fired instantly: `was=0.0 now=10.0`,
   `was=5.0 now=20.0` — the bots were tracking 5 while holding 20.
2. **Too fast.** At 5s, two bots hit HTTP 429, the reconcile failed
   intermittently and eth drifted to inv=45 against a 30 cap.
3. **Shared egress.** Both pods leave via one IP, so at 15s each eth logged 11
   consecutive 429s and ZERO reconciles. **Fix: 30s base, STAGGERED per coin
   (`hash(COIN) % 2 * 15`), exponential backoff to 120s on 429.**

**⭐⭐ THE LESSON (twice now): an unverified safety mechanism is worse than
none — it reports healthy while protecting nothing.** Both times the loop ran
clean with zero errors and did nothing. Only testing the code path directly
(fetch the URL, compare the keys, count matching rows) exposed it. Never accept
"no errors in the log" as evidence a guard works.

### Open / watch
- Cap overshoot persists in VOLUME (a 65-share bar vs SIZE=10) but NOT in
  imbalance — unpaired sits at exactly BATCH_SH=5. Neutrality is intact; the
  binding constraint is capital, not risk. `MAX_INV_SH` 30→20 is the knob if
  turnover needs capping.
- UMA 600s liveness means inv can stay high into the next bar and block early
  quoting; watch that resolve_loop clears it (reconcile only adds).
- Raise SIZE 10→25 (volume) only while BATCH_SH stays 5 (neutrality) — they are
  independent knobs — and only after a clean day with the reconcile healthy.

## ⛔ HALTED 2026-08-21 22:20 Kyiv — conclusively characterised, not merely unproven

Ran ~28h / 24 bars, btc (+eth for ~5h). Stopped by user after the mechanism was
measured. **The sim is CALIBRATED to live** — sim −$0.246/bar vs live
−$0.238/bar (3% agreement, 35 resolved bars). First time in this program a
backtest reproduced live PnL, so its verdicts below are trustworthy.

### The mechanism, measured (`pairceil1h.py`)
We quote 1.5c BELOW the mid; **our fills land 0.47c ABOVE it, and 48% of fills
execute above the prevailing mid.** That is not a bug — it is what a resting
order *is*. Nothing happens while the mid sits still; you get filled when the
mid FALLS TO YOU, at which point you are no longer below it.

⇒ **−0.47c of adverse selection per fill vs a +0.35c rebate.** That single
number is why no parameter works, and it explains the field-vs-sim gap that
confused this whole program: the archive's profitable "1-1.5c depth" fills
(+1.047 c/sh) are makers filled WITHOUT the mid moving; ours are the opposite
population — filled BECAUSE it moved. Same book, opposite selection.
Quoting DEEPER makes it worse (e=2.5c ⇒ fills at −1.15c, 59% above mid):
depth does not buy a better price, it buys a worse selection.

### Everything measured and refuted (1h btc, 304 bars unless noted)
| lever | result |
|---|---|
| PAIR_CEIL 0.985 → 1.10 → OFF | best OFF, −$0.103/bar; ceiling ON ⇒ good pairs (+$175) + ruinous residual (−$250); OFF ⇒ no residual but pairs below par (−$58). **Mutually exclusive by construction.** |
| EDGE_C 0.3c → 2.5c | shallow better; all negative |
| exit naked leg near bar close | WORSE (−0.246 → −0.413) |
| cut naked leg 5-180s after fill | catastrophic (−$3.07/bar); **RAND identical to real ⇒ pure transaction cost** |
| TAKER completion (buy missing side) | residual → **0%** as designed, but −$0.28/bar; **RAND identical to real** |
| volume scaling (size 10→20→40) | loss/share ~constant −0.53…−0.74c; **doubling volume doubles the loss** |
| volatility gate on entry | no predictive power (corr −0.056); 87% of bars DO oscillate enough to pair |
| mint/merge "atomic pair" | **NOT a distinct mechanism** — book is 100% mirrored (34,526 snaps: DOWN bid ≡ 1−UP ask), so an ask on UP at `a` IS a bid on DOWN at `1−a` |
| 15m (same harness) | −$0.160/bar × 96 bars = **−$15/day**, worse than 1h in absolute terms |

**Invariant across every test: RAND is positive (+$0.50…+$0.89/bar), real is
negative.** The mechanical structure is +EV; real outcomes destroy it through
the one leg that fails to pair.

### ⭐ The general rule (third derivation, now with numbers)
**Any action priced by the market — selling the leg, completing it as taker,
hedging it — costs exactly what the position is already worth.** Only the
ACQUISITION price matters, and a resting order acquires at a systematically
adverse moment. (Same rule as strat-openmm-5m §11b; re-derived here because I
forgot it and re-tested exits twice.)

### Final ledger
Net worth $114.69 → ~$107.5 over ~28h = **−$7.2** (−6%). 24 bars, 23 paired,
mean pair sum 0.972, 1 halt (eth, correct), 0 crashes, 0 code defects after the
reconcile fixes. Cost of the finding: ~$7. Compare the 5m pilot: −$53.78.

### Still open
**4h is the only untested duration** (recorders live since 08-17; ~14 bars as
of 08-21 — far too few). Highest pair completion, smallest residual, and 6
bars/day makes even a negative result nearly free. Retest with
`pairceil1h.py` (change BAR/dir/prefix) once ~2 weeks of mrec4h exists.
⚠️ But note the mechanism above is duration-independent: a resting order fills
when the mid comes to it at ANY bar length. Expect 4h to be better only if its
spread exceeds the adverse selection, which 5m/15m/1h all failed to do.
