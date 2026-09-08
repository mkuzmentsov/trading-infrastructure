# 5m EDGE HUNT — non-maker options, venue mechanics, taker-lane improvements (2026-09-07 → 09-08)

**Mandate (user):** *"another agent to investigate other options. search for edge and any mechanics to
abuse. Check for trading strategies we can use. only 5m."* Maker lanes are in
[strat-maker-tickjump-20260907](strat-maker-tickjump-20260907.md); this doc is everything else.
**Data:** mrec v2 parquet (7 coins, 09-01→09-06, 9,833 bars, 2.73 M prints; raw `mrecev` event streams
for tick-size events), **the 7 live vacmaker ledgers pulled read-only 09-07 ~23:30 K (08-17→09-07,
7,809 orders / 3,939 settles; current era ≥08-22 = 2,456 fills, +$248.97, 17 days = $14.65/day)**, and
a 200-bar data-api wallet sample. Scripts: `winner-vacuum/tools/mrec/edgehunt/`.

## 0. VERDICT TABLE

| # | lead | verdict | key number |
|---|---|---|---|
| 1a | `tick_size_change` transient to hit | ⛔ nothing | **0 crossed/locked books in 10,188 events**; prints above the pre-change ask are the loser at 0.01→0.011 |
| 1b | post-close prints (T+0 → resolution) | ⛔ taker-dead, maker-only pool | 7,059 prints / 1.67 M sh post-close; **99.98 % of shares are SELLS of the winner into 0.98-0.999 bids**; taker-liftable winner asks = **$272 / 6 d whole field** |
| 1c | cheap-extreme mispricing (loser asks ≤0.10 late) | ⛔ −0.9 to −7 c/sh every cell | flip rate 0.003-0.04 % vs 0.86-0.94 % break-even at 0.01 |
| 1d | orders after close / T+2 → redemption timing | ⛔ no arb | orders ARE accepted post-close (626/628 rest orders got ids at T+2.1 s) but nothing takeable exists |
| 1e | min size / dust | ⛔ | `orderMinSize` 5 sh; venue fills partials down to 0.03 sh; the only dust flow is the field buying the LOSER at 0.001 post-close (−EV lottery) |
| 1f | wash / self-trade / new archetypes | ⛔ none new | late takers = 0.99-lifters (top wallet $2.9 k/11 bars @0.990); 186/3,631 wallet-bars two-sided = MMs, not wash |
| 2 | cross-coin est / 15m as signal | ⛔ | btc sign right about an alt **77.4 %** vs the alt's own est **97.7 %**; when both decisive and disagree, own est wins **97.6 %** |
| 3a | "fire only at displayed 0.99" | 🟡 informative, not a gate | 0.99: 892 fills, 9 losses, +$139.64, **1.19 %**; 0.98: 797, 10, +$75.03, 0.63 % — the restriction forfeits $75 |
| 3b | tl≤12 vs 16-20 A/B | ⛔ **undecidable live** | per-bar ROI sd 17.4 pp ⇒ +0.8 pp needs **858 coin-days per arm** (~4 months) |
| 3c | clip size vs sweep option | ✅ confirms §5 of the live ledger | sweep ROI by requested size 2.3 % → 8.9 % → 20.3 % → **35.0 %**; sweeps fill **1.36×** the request |
| 3d | ledger fields not yet exploited | 🟡 two closures, no new lever | UTC 03-11 "hole" = the mid-band bleed (post-08-31 **+1.01 %**); ladder = net **+$0.05 / 17 d** but post-gate **+$61** |
| 4a | widen the fire window to tl 0 / T−2 | ⛔ | favourite ask displayed in **1.1 %** of tl<3 seconds; house-model replay +13 clips / 6 d = **+$0.26/day** |

**Nothing here is a new strategy.** The 5m taker lane's remaining levers are the ones the live ledger
already named (clip size at displayed ≥0.98, §5), and two open questions in the decision map are now
closed (the UTC hole, the tl A/B).

---

## 1. Venue mechanics

### 1a. `tick_size_change` — 41,113 events, none abusable
Raw `mrecev` streams carry the venue event verbatim. 41,061 are 0.01→0.001, **52** revert. Timing
relative to the tagged bar: **75 % fire after the close** (median tl −40 s — the loser going to
0.01 and the winner to 0.99 post-close), 7,208 in-bar, 3,022 of those at tl ≤ 30.
For 10,188 events with a same-market, same-token book event inside [−3, +5] s (`tsc_an3.py`):

| | |
|---|---|
| best bid ≥ best ask (crossed / locked) in the 5 s after | **0 of 10,188** |
| a 0.001-grid level appears within 5 s | 29 % |
| BUY prints above the pre-change ask within 5 s | 730 prints / 32,319 sh — the LOSER at 0.01 → 0.011-0.02, i.e. the fine tick *moving* the price, not a stale 0.01-grid ask left behind |
| SELL prints below the pre-change bid | 12 |
| pre-change book (in-bar) | bid 0.90 (mode) / ask 0.01 (loser) or 0.99 (winner) |

⚠️ *Correction to the first pass of this analysis:* filtering the window on token label only mixed the
`cur` and `post` markets (both have a token called `U`) and produced a fake "book at 0.40/0.51 at the
change" picture. **Window rows must match `ws` AND `tok`** (→ proposed bug #39).
**For Agent A:** the fine tick appears in-bar on **both** tokens (loser < 0.04, winner > 0.96) and
only 39 % of in-bar events are on the eventual winner; there is no transient to exploit, and the tick
change does *not* cancel 0.01-grid resting orders (no book gap, no crossed state).

### 1b. Post-close — a maker pool, not a taker one
`trades.parquet`, tl < 0, 6 days: **7,059 prints / 1,672,883 shares**, winner-space price 0.98-0.99
(4,269 prints) or 0.995-1.0 (2,735). Taker action on the WINNER token:

| taker action | prints | shares | notional |
|---|---|---|---|
| SELL the winner (dump into a resting 0.98-0.999 bid) | 6,901 | **1,631,551** | $1,625,491 |
| BUY the winner (lift a displayed ask) | 124 | 38,541 | $38,248 |

The BUY-winner pool — the only thing a taker can touch — is worth **$272 over 6 days fee-inclusive**
(btc 22.6 k sh in 6 bars, hype 329 sh in 12 bars). Winner asks ≤0.95 post-close: **15 prints /
1,342 sh / $124 of value in 10 bars**. This reconfirms §52-56 (snipe 0/205, rest 0/165) from the
tape side: **post-close, the whole market is sellers dumping the known winner into 0.99 bids** —
the maker's lane (Agent A, §54: queue-starved), never the taker's.

### 1c. The cheap extreme — underdog asks ≤0.10, tl 2-40 (`panel`, `evage<1`, displayed ≥8 sh)
| tl | ask ≤0.01 | 0.01-0.02 | 0.02-0.03 | 0.03-0.05 | 0.05-0.07 | 0.07-0.10 |
|---|---|---|---|---|---|---|
| 2-10 | flip 0.003 % / BE 0.86 % → **−0.86 c** | 0 % → −2.14 | 0 % → −3.19 | 0 % → −4.27 | 2.2 % → −3.49 | 1.7 % → −6.81 |
| 10-20 | 0.008 % → −0.89 | 0 % → −2.14 | 0.6 % → −2.62 | 0 % → −4.27 | 1.5 % → −4.31 | 4.8 % → −3.58 |
| 20-30 | 0.031 % → −0.89 | 0.25 % → −1.89 | 0.7 % → −2.51 | 1.9 % → −2.38 | 2.4 % → −3.59 | 1.4 % → −7.03 |
| 30-41 | 0.038 % → −0.90 | 0.67 % → −1.47 | 1.8 % → −1.36 | 1.5 % → −2.80 | 2.3 % → −3.61 | 3.1 % → −5.40 |

(≈32 k observations per cell at ≤0.01; 50-1,800 elsewhere.) Every cell negative. The one positive
cell — est disagrees with the market favourite, tl 10-20, **24 bars**, flip 6.3 % vs 4.6 % BE — is
noise at that n. ⭐ The **0.003-0.04 % flip rate of a favourite whose underdog ask is ≤0.01** is the
cleanest statement of how safe the late 0.99 favourite is (cf. Agent A's tick-jump loss-rate bound).

### 1d. Resolution / redemption timing — no arb
The live rest lane proves orders are accepted after close (626 of 628 `PF_TE_SNIPE_REST` orders
received an order id, placed at T+2.1 s median). Between T+2 (winner known 99.98 %) and resolution
(`post_secs` median 308 s) the only prints are §1b's — nothing takeable. Redemption lands ~2 min
after close (§41); with ≤30 s holds and 7 bars closing on one boundary the binding constraint is
**concurrent exposure (7 × clip)**, not timing.

### 1e. Minimum size / dust
`orderMinSize` = 5 shares (`core/pm_ws.py`, fallback 5); the venue fills FAK partials down to
**0.03 shares** (live `filled` min) — no rounding asymmetry to exploit. The field's dust flow is
buying the **loser at 0.001 post-close** (10,000-share prints, $10 for a 1000:1 ticket on a
resolution flip): break-even flip 0.1 % vs the observed **0.016 %** (2/12,281, §openlag). −EV.

### 1f. Wallet archetypes, 200 sampled bars (6,502 late prints, 1,701 wallets)
Late (tl 0-30) taker notional $30 k; top-10 wallets = 33 %. Archetypes, in order: **0.99-lifters**
(Warlike-Fallingout $2.9 k in 11 bars @0.990 / 100 % win; Bright-Jasmine $1.5 k / 9 bars), **cheap
late lifters** (Vibrant-Motorcycle $425 @0.825 +$114; Imperfect-Tolerance @0.788 +$126 — the sweep
class), **0xefdf6abc** (35 prints, $261, @0.985, 100 %), and MMs printing both sides (186 of 3,631
wallet-bars — e.g. 0xcbedda… 18 BUY/9 SELL in one btc bar). **No wash/self-trade pattern, no new
archetype since August**; the data-api cap (1,000 trades/market, hit on 67 % of bars) truncates
the busiest bars, so this is a lower bound on MM activity, not on takers.

## 2. Cross-market signals — dead by construction
- **btc → alt:** at the same (ws, tl) the btc est's sign is right about an alt **77.4 %** of the
  time (bnb 75, eth 83, hype 70) vs the alt's own relay-lagged est **97.7 %**. Where both are decisive
  and disagree (35,068 rows / 1,509 bars) the alt's own est is right **97.6 %**, btc's **2.4 %**.
  Where the alt's est is unusable (cov<0.5) btc's decisive sign is right **70 %** — worse than the
  alt's own market favourite. Spot correlation cannot beat the alt's own Chainlink ticks.
- **15m/1h → 5m:** the 5m settles on its own TWAP-60 of Chainlink ticks the bot already has; a
  longer market's price adds nothing about those ticks. Not tested — no mechanism.

## 3. The live taker lane (7 ledgers, current era ≥08-22, 2,456 fills)

| class | fills | losses | cost | pnl | ROI |
|---|---|---|---|---|---|
| SWEEP (≥5 % below displayed) | 59 | 16 | $781 | **+$136.15** | 17.4 % |
| filled ABOVE displayed | 475 | 14 | $6,663 | +$41.66 | 0.63 % |
| filled AT displayed | 1,922 | 61 | $23,993 | +$71.16 | 0.30 % |

### 3a. "Fire only at displayed 0.99 exactly"
| displayed | fills | losses | pnl | ROI | days + |
|---|---|---|---|---|---|
| 0.97 | 241 | 10 | −$40.53 | −1.57 % | |
| 0.98 | 797 | 10 | +$75.03 | 0.63 % | 12/17 |
| **0.99** | 892 | 9 | **+$139.64** | **1.19 %** | 13/17 |
| ≥0.98 (live) | 1,698 | 19 | +$216.31 | 0.91 % | 12/17 |

By tl at 0.99: **tl ≤12 → 7.78 % (66 fills, 1 loss)**, 12-16 → 1.22 %, 16-20 → 0.56 %; at 0.98:
2.12 / 1.22 / 0.29 %. Sweeps from a displayed 0.99: 14 fills, 0 losses, +$136.95 (all of the
class's profit); from 0.98: 6 fills, 2 losses, −$19.83. **Restricting to 0.99 forfeits the 0.98
cell's +$75** — it is a *sizing* signal (size 0.99 up, per §5 of the live ledger), not a gate.
Per coin at 0.99: bnb +5.6 %, btc +3.8 %, hype/sol +1.0 %, eth +0.4 %, xrp −1.3 %, doge −1.4 %.

### 3b. tl ≤12 vs 16-20 — the A/B cannot be run in useful time
The gradient is real in the ledger (≥0.98 band: tl 0-12 **+4.81 %** 136 fills 1 loss; 12-16
+1.22 %; 16-20 +0.43 %, 1,276 fills, 16 losses). But the per-bar ROI in the 16-20 cell has
**sd 17.4 pp** (1,032 bars, 8.7 bars/coin-day). A two-arm test at 80 % power needs
**858 coin-days per arm for +0.8 pp** (549 for +1.0 pp, 2,196 for +0.5 pp) — with the fleet split
3/4 that is **~4 months**. §8/§9's question will not be settled by a live A/B; the delay decision
has to be made on the observational gradient plus §9's paired counterfactual, or not at all.

### 3c. Clip size vs the sweep option
Sweeps fill **1.36× the requested shares** (a $-sized FAK at a stale price buys more shares); sweep
ROI by requested size: ≤9 sh **2.3 %** · 9-13 **8.9 %** · 13-25 **20.3 %** · 25-100 **35.0 %**.
PnL per $ requested across all sweeps = **0.176**. Linear-or-better in size — consistent with §5.

### 3d. Ledger fields — two closures
- **UTC 03-11 "hole"** (open lead in `analytics-20260830`): live it is **−$85 / 763 fills**, 11 of
  17 days negative — but it is the **mid-band bleed**: pre-08-31 −$137, **post-08-31 +$52 (1.01 %)**
  vs rest +$194 (1.60 %); the house-model replay shows 0.09 % vs 0.67 %, and the field's late
  favourite lifts are *better* in the hole (win 0.9939 vs 0.9924). **No time-of-day gate.**
- **Ladder clips (clip ≥2):** 762 fills, 20 losses, **+$0.05 net over 17 days**; ex the single bnb
  0.238 windfall (+$76.09) it is −$76. But the negative half is again pre-08-31 mid-band
  (−$82); post-08-31 the ladder is **+$61 on 74 fills**. Restricting it to displayed ≥0.985 looks
  like +$58 vs −$58 but is one windfall (ex-max −$17.5) and LOO-bnb −$20. **Leave the ladder alone.**
- `ms` (order round trip, p50 353 ms) is unrelated to the sweep rate (1.1-3.2 % across quartiles,
  noise) and to ROI. `disloc` orders: 3,687 attempts, 44 % matched, mean cost $6.9 — inside §48.
- Live match rate by displayed ask (all attempts, current era): <0.75 **27 %** · 0.75-0.90 16 % ·
  0.90-0.95 45 % · 0.95-0.98 60 % · 0.98-0.985 50 % · **0.985-0.995 72 %**.

## 4. Widening the fire window below tl = 3
The field lifts **46,555 winner shares at ≤0.99 in tl [0,3)** (129 bars / 6 d) and 15 k in
[−2, 0) — but the favourite's ask is **displayed in only 1.1 % of tl<3 seconds** (3.2 % at 3-12,
7.0 % at 12-20). House-model replay (`latesim2.py`, panel tlk 0-90, FILLW 0.4 s, fill AT ask,
tape-sized, live gate): tl 3-20 baseline 557 clips / +$39.06 / 4 of 6 days; **adding tl 0-2 =
13 clips / +$1.28 / +$0.26 per day**, and as a ladder position it *lowers* the 0-20 total to
+$17.17 (second clips at ≥0.94 in the last seconds lose). The asks the field lifts there exist for
less than one 100 ms snapshot. ⛔.

## 5. Notes for Agent A (maker)
1. §1c: P(flip | underdog ask ≤0.01 displayed, tl<10) = **0.003 %**; tl 20-30 = 0.031 %. Use as the
   loss-rate prior for a 0.99x resting bid instead of the 6-day observed count.
2. §1a: in-bar `tick_size_change` fires on both tokens; the 0.001 grid is live on the winner in
   only a fraction of bars before tl 30 — round the rest price DOWN to the token's current tick
   (notes §24) and log rejections.
3. §1b: the post-close SELL-the-winner flow is 1.63 M sh / 6 d at 0.98-0.999 — the maker pool §54
   was queue-starved in; a 0.001 improvement post-close has never been measured.

## 6. What this leaves
The 5m taker program has **no unexploited mechanic** in the venue's order lifecycle, fee schedule,
tick regime, resolution window, or size rules, and no cross-market signal. Its remaining money is
where the live ledger already put it: **sizing the displayed-0.99 clip** (§3a/3c) — and even that
is a fat tail in both directions, to be sized against the fleet's 1.19 % loss rate, not btc's 0.

---

## Proposed README rows (Agent B — for the coordinator to merge)
| If considering… | Verdict | Why (one line) | File |
|---|---|---|---|
| **Any venue MECHANIC to abuse on 5m** (tick_size_change transient, post-close window, cheap-extreme mispricing, order acceptance after close, min-size/dust, wash flow) | ⛔ **NONE (2026-09-08)** | 41,113 tick-size events: **0 crossed/locked books**, no 0.01-grid asks left behind; post-close 1.67 M sh = **99.98 % sellers dumping the winner into 0.99 bids** (taker-liftable $272/6 d); underdog asks ≤0.10 late: flip 0.003-0.04 % vs 0.9 % BE, **every cell −0.9…−7 c/sh**; post-close orders accepted (626/628) but nothing takeable; `orderMinSize` 5, partials to 0.03 sh; late takers = 0.99-lifters, no wash | [strat-edge-hunt-5m-20260907](strat-edge-hunt-5m-20260907.md) |
| **Cross-coin / cross-duration signal for the 5m late window** | ⛔ NO (2026-09-08) | btc est sign right about an alt 77 % vs the alt's own est 98 %; when both decisive and disagree, own est 97.6 % / btc 2.4 %; 15m/1h add nothing about the 5m's own TWAP ticks | [strat-edge-hunt-5m-20260907 §2](strat-edge-hunt-5m-20260907.md) |
| **The tl≤12 vs 16-20 single-coin A/B (§8/§9)** | ⛔ **UNDECIDABLE LIVE (2026-09-08)** | per-bar ROI sd 17.4 pp in the 16-20 cell ⇒ +0.8 pp at 80 % power needs **858 coin-days per arm ≈ 4 months**; decide on the observational gradient (tl 0-12 +4.81 %, 136 fills, 1 loss) or not at all | [strat-edge-hunt-5m-20260907 §3b](strat-edge-hunt-5m-20260907.md) |
| **A UTC time-of-day gate (the 03-11 "hole")** | ⛔ CLOSED (2026-09-08) | the hole was the mid-band bleed: pre-08-31 −$137, **post-08-31 +$52 (1.01 %)** vs rest 1.60 %; replay 0.09 vs 0.67 %; field lifts *better* in the hole | [strat-edge-hunt-5m-20260907 §3d](strat-edge-hunt-5m-20260907.md) |
| **"Fire only at displayed 0.99" / widen the window to tl 0** | 🟡 sizing signal, not a gate / ⛔ | 0.99: +$139.64, 1.19 %, 13/17 days (tl≤12 **7.78 %**) vs 0.98 +$75, 0.63 % — the restriction forfeits $75; sweeps scale 2.3 %→35 % with requested size; tl 0-2 adds 13 clips / +$0.26 per day (ask displayed 1.1 % of seconds) | [strat-edge-hunt-5m-20260907 §3a/§4](strat-edge-hunt-5m-20260907.md) |

## Proposed bug-ledger entries
**Bug #39 (2026-09-08, edgehunt): raw-event windows must be keyed on (ws, tok), not tok.** The `cur`
and `post` markets are recorded simultaneously and both carry tokens labelled `U`/`D`. A window
filtered on token alone mixed the new bar's opening book (0.40/0.51) into the post-close tick-size
events and produced a fictitious "book at 0.40/0.51 at the tick change" — 33,393 "matched" events
became 10,188 real ones after the `ws` filter. Rule: every join against the raw `mrecev` stream
keys on `(coin, ws, tok)`; `bookev.parquet`/`trades.parquet` already do, the window extractor did not.

**Bug #40 (2026-09-08, edgehunt): a live A/B must be POWERED before it is designed.** The 16-20
cell's per-bar ROI sd (17.4 pp) makes a +0.8 pp effect need 858 coin-days/arm. Any proposed live
A/B in this program must state n-per-arm from the ledger's per-bar sd first; if it exceeds ~30
coin-days/arm it is an observational study, and should be written up as one.

## Appendix — inline censuses (verbatim pandas; `pq` = the mrec build, `fills_era.parquet` from `led_an.py`)
- post-close prints: `t[t.tl<0]`, taker action mapped to winner space (`BUY winner ≡ SELL loser`).
- underdog grid: `panel`, `evage<1`, `dog_ask = da if ub>=db else ua`, `flip = dog won`, `BE = px + 0.07·px·(1−px)`.
- cross-coin: `panel` self-merge on `(ws, tlk)` against btc's `side`/`est_bps`/`cov`.
- UTC hole: `hr ∈ [3,10]` on `fills_era` split at 08-31; permutation null over bars.
- ladder: `clip>=2` on `fills_era`, split `seen_ask>=0.985`, LOO-coin, ex-max.
