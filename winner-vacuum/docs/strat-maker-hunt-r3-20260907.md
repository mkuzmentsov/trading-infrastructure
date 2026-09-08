# Maker hunt, round 3 (agent A) — the tick-jump lane is 98.6 % INFEASIBLE: the venue flips the tick ~2 minutes late — 2026-09-07

**Mandate:** *"investigate maker 5m opportunities … search for edge and any mechanics to abuse … only 5m."*
**Data:** mrec v2 parquet (7 coins, 09-01 → 09-06, 9,833 bars, 2.73 M prints), `bookev` event book,
`lad10` 10-level ladders, `rb` REST reconciles, and — new here — **the raw `tick_size_change` WS
events** from every `<coin>-mrecev-*.jsonl.gz` (16,212 flips, venue-timestamped).
**Scripts:** `winner-vacuum/tools/mrec/tickjump/agentA/` (`a1`…`a14`, `lw4`). Discipline per
`/sim-validity`: terminal PnL with the 3-term decomposition (bug #37), queue-ahead, tape-size cap,
`evage<1s`, bar-clustered SE, per-day + leave-one-coin-out on every positive cell, pre-registered
gates (two, declared before running), loss EVENTS counted.

---

## 0. VERDICTS IN ONE TABLE

| lead | verdict | the number |
|---|---|---|
| **1. Tick-jump lane (0.991 bid, tl 2-30)** | ⛔ **INFEASIBLE as simulated — 98.6 % of its fills happen while 0.991 is an ILLEGAL price** | tradeable subset = **34 bars / 6 days, +$1.7/day** (was +$74) |
| 1 (mechanism) | ✅ every *other* attack passed — hidden queue, competition, capacity, gates, sides | 98.1 % of prints AT the best bid; 12 improvers in 3,905 bar-tokens; G2 gate → 2 loss bars |
| **2. Mirror lottery (underdog bid at 0.002)** | ⛔ dead by capacity | 2,741 sh / 6 d, **0 win events**, −$0.56/day; pool 2,360 sh/day |
| **3a. Rebate-farm §7 "first-60s two-sided" cell** | ⛔ **−4.40 ± 0.72 c/sh, 0/6 days** on terminal (was "+$45/day") | drift −4.53 c/sh was the whole story |
| **3b. Rebate-farm ".04-.15 cheap band"** | ⛔ **−2.23 ± 0.44, 0/6 days** (was "+0.150") | drift −2.22 |
| 4a. tick_size_change transient | ⛔ the flip is the *blocker*, not an edge | venue flips **120 s (p50) after** price crosses 0.96; 74 % of flips are **after close** |
| 4b. post-close winner bid (snipe-rest's lane) | ⛔ §56 confirmed from the tape | pool $217/day exists but **$187 of it is in coarse-tick bars** where 0.991 is illegal; in fine bars best bid is already 0.999 |
| 4c. post-close flip window (0.991 at the flip instant) | ⛔ | **3 prints in 6 days** — post-close sellers only appear after somebody improves (median 18 s) |
| 4d. 0.999 exit for a tick-jump fill | ⛔ | ≥0.999 buy demand after our fill exists in **0.8 %** of bars |
| 4e. minted-pair 0.999 ask | ⛔ by identity | fav ≥0.999 + loser ≤0.001 = **1.000** exactly |

**The one thing to tell the user:** the tick-jump edge is real in the book but **not reachable on this
venue's clock** — Polymarket switches a market to the 0.001 tick only ~2 minutes after the price
first crosses 0.96, and the bar is usually over by then. Only **13 % of decisive bars** have the fine
tick by tl = 30 (6.6 % by tl = 60). The parent doc's +$74/day was computed on prices the venue would
have rejected (`"invalid price, max: 0.99"` — §24/§56 saw exactly this live).

---

## 1. Lead 1 — hardening the tick-jump lane

### 1a. Hidden queue — PASSED (`a1_book.py`, event book + tape)
Sell pressure on a favourite token with `b0 ≥ 0.98`, tl 2-30: **15,256 prints / 2.05 M shares**.

| print executed | prints | shares |
|---|---|---|
| **exactly at the displayed best bid** | **98.09 %** | 89.84 % |
| above it (someone had improved) | 0.99 % | 7.03 % |
| below it (walked through) | 0.92 % | 3.13 % |

At-best-bid prints fit inside the displayed size **97.7 %** of the time; the level survives the print
61.8 %; **median displayed queue at the best bid = 7,647 shares vs a median print of 12** — joining
is hopeless, improving is the only way in. Nothing hidden: a print at the best bid is a taker sell
against displayed depth, and a bid one tick better would have been matched first.

### 1b. Competitive response — PASSED (nobody is doing this)
Best-bid improvements on the favourite inside tl 2-30: **853 in 3,905 bar-tokens**, but **629 are +0.010
and 176 are +0.009** (grid moves 0.98→0.99, 0.99→0.999). **Exactly-+0.001 improvements: 12 (0.3 % of
bar-tokens)**, median size 21 sh. Only 7.4 % of prints (28.8 % of shares) arrive when the best bid is
already off-grid — and that is almost entirely the 0.999 level. After an improvement, a further
improvement follows within 1 s in **1.2 %** of cases. The niche is empty. (It is empty because of §2.)

### 1c. Capacity at pilot sizes (`a2_cap.py`)
Qualifying pressure per filled bar: p10 3 · p25 10 · **p50 100** · p75 500 · p90 1,508 sh; 85 % of
filled bars have ≥5 sh, 61 % have ≥50.

| clip | $/day (as simulated, ignoring §2) | net c/sh |
|---|---|---|
| 5 sh | +10.9 | +0.584 |
| 8 | +16.1 | +0.565 |
| 12 | +22.3 | +0.545 |
| 24 | +39.3 | +0.522 |
| 50 | +74.2 | +0.518 |

### 1d. The loss events, and two PRE-REGISTERED gates (`a3_loss.py`, `a10_persist.py`)
All 8 losing bars (G0), with the fleet's relay-lagged estimate at the fill and at tl 25/15/5:

| coin | side | q | sh | tl | est_bps@fill | cov | est@25 | est@15 | est@5 |
|---|---|---|---|---|---|---|---|---|---|
| bnb | D | .991 | 50 | 20.2 | −1.14 | .68 | −1.14 | −1.01 | −0.30 |
| doge | D | .991 | 16 | 26.1 | −4.79 | .59 | −4.65 | −2.78 | −0.20 |
| doge | D | .991 | 50 | 27.5 | −3.55 | .56 | −3.49 | −0.72 | **+1.23** |
| eth | U | .991 | 50 | 19.5 | +1.00 | .70 | +0.97 | +0.74 | +0.15 |
| eth | U | .987 | 50 | 25.7 | +1.92 | .58 | +1.93 | +1.81 | +0.71 |
| hype | U | .991 | 31 | 27.0 | +3.98 | .58 | +3.57 | +0.03 | **−2.55** |
| hype | U | .991 | 50 | 12.7 | +1.59 | .78 | +1.48 | +1.59 | +0.63 |
| sol | U | .991 | 50 | 7.0 | +0.65 | .81 | +2.89 | +1.65 | +0.53 |

Six of eight are margins that **decay toward zero** after the fill (the estimate was right at fill
time and the TWAP drifted) — no gate at the fill instant sees them; the two decisive flips
(doge +1.23, hype −2.55 at tl 5) are late reversals. Gates declared before running: **G1** = the
fleet's `|est_bps| ≥ 2, cov ≥ 0.5`; **G2** = *the best bid must have been ≥ 0.98 for ≥ 5 s before we
quote* (backward-looking, no tuning).

| gate | bars | sh | q | win | net c/sh | $/day | loss bars | LOO-btc $/day |
|---|---|---|---|---|---|---|---|---|
| G0 none | 2,467 | 85,924 | .9898 | .99480 | +0.518 ± .169 | +74.2 | 8 | +3.2 |
| G1 | 1,604 | 51,432 | .9909 | .99811 | +0.738 ± .119 | +63.2 | 3 | +29.0 |
| **G2 persist ≥5 s** | 2,041 | 72,277 | .9908 | .99909 | **+0.839 ± .073** | **+101.1** | **2** | **+36.1** |
| G1+G2 | 1,466 | 48,219 | .9910 | .99967 | +0.878 ± .033 | +70.5 | 1 | +29.0 |

G2 is the better gate: it removes 6 of 8 losses while *adding* $/day (the losses were −$300 of the
−$344 downside), makes **all seven coins positive** (btc $390, eth $76, sol $68, xrp $43, hype $15,
bnb $14, doge $2 per 6 d) and lifts LOO-btc from +$3 to +$36/day, 6/6 days. Sensitivity curve (a
curve, not a fit — 5 s was the pre-registered value): PERSIST 0/2/5/10/15/20 s → loss bars
8/6/2/1/1/0, $/day 74/88/101/92/79/70. ⚠️ The t-statistics at G2 and beyond (11.5, 34.5, 804) are
**loss-count artefacts** and must not be quoted as significance.

### 1e/1f. Window and side
tl 30-60: **+0.061 ± 0.249** (dead); 45-60 +0.257 ± 0.281; 60-90 −0.036. The edge lives only in
**tl 2-30**. UP-token bids +0.382 ± 0.275, DOWN-token bids +0.648 ± 0.200 — both positive, the
difference is 0.8 σ; no asymmetry claim.

---

## 2. ⛔⛔ THE KILL — the 0.001 tick is a venue REGIME that arrives ~2 minutes late (`a11`, `a12`, `a13`)

The parent sim placed `best_bid + 0.001` whenever the favourite's bid was ≥ 0.98. But Polymarket's
0.001 tick is **per-market state** switched by a `tick_size_change` event; before it, **0.991 is
rejected** (`"invalid price, max: 0.99"`, notes §24; §56: *"coarse bars: 0.991 illegal there"*).
The raw recorder event stream has every flip, venue-timestamped (`m.timestamp`; recorder receive
lag 20 ms):

| | |
|---|---|
| 0.01 → 0.001 flips recorded | **16,212** events / **7,729 bars** (asset-id-mapped to the bar) |
| flip time minus **bar close** | p10 −38 s · p25 −1.5 s · **p50 +36 s** · p75 +82 s · p90 +109 s |
| flips **before close** | **25.5 %** — before tl 30: **13.0 %** — before tl 60: 6.6 % — before tl 120: 2.4 % |
| flip minus first fav **bid ≥ 0.96** | p10 64 s · **p50 121 s** · p90 180 s |
| flip minus first **print** > 0.96 | p10 68 s · p50 126 s · p90 192 s |
| fav bid at the flip instant | 0.99 (1,909) — and **0.00 (5,631)**: the market had already closed |
| flip time modulo 60 s | flat (not a cron); it is a ~2-minute lag behind the price |

So the flip lags the price crossing 0.96 by about two minutes, and a bar that becomes decisive in its
last two minutes closes on the coarse tick. **Only 11.9 % of bars with fav bid ≥ 0.98 inside tl 2-30
have the fine tick by tl = 30** (btc 14.6 %, sol 15.5 %, eth 14.9 %, xrp 13.4 %, bnb 10.4 %, hype
8.9 %, doge 6.9 %).

### The tradeable subset of the parent's fills (fill instant ≥ venue flip + 0.2 s)

| config | as simulated | **tradeable** |
|---|---|---|
| G0 | 2,467 bars · +$74.2/day · 8 losses | **34 bars · +$1.7/day** · 0 losses · LOO-btc +$0.8 |
| G2 | 2,041 · +$101.1 · 2 | **26 · +$1.3** · 0 |
| G1+G2 | 1,466 · +$70.5 · 1 | **20 · +$1.1** · 0 |

Tradeable fills happen a median 53 s after the flip, at tl ≈ 25 — i.e. only in bars that were decided
by tl ≈ 150. Per coin over 6 days: btc $5.7, sol $2.2, hype $2.1, eth $0.4, bnb $0.1, doge $0.0.

**This is bug #39 (proposed below): a price must be legal at the instant it is placed, and on this
venue legality is a lagged state, not a function of the current price.** The parent's fill-model
diagnostic (94.7 % of prints at the best bid) was correct and is why the lane *looks* empty: it is
empty because the price everyone would need is illegal for most of the window, not because nobody
thought of it. This also explains 1b (nobody improves) and reconciles §56's live 0/165.

### Is the lag exploitable? — No (`a14_flipwindow.py`)
At the flip instant the entire 0.99 queue (7,600 sh) is on the coarse grid and the first 0.991 order
front-runs it. Someone improves within a median **18 s** in 51 % of flip bars. Winner SELL prints at
≤ 0.991 inside `[flip, first improver)`: **896 prints / 664 sh/day — $6/day pool, $1.4/day at a
50 sh cap; post-close: 3 prints in six days.** Post-close sellers only appear once the 0.999 bids are
up. Nothing to abuse.

---

## 3. Lead 2 — the mirror lottery (`a4_mirror.py`)
The 0.001 grid **does exist below 0.04** (underdog best bid = 0.001 in 20,323 decisive snaps, 0.010
in 17,112; 9.6 % of `ub < 0.04` values are off the 0.01 grid). Displayed queue at 0.001-0.009 is
thin (median 10-13 sh, 4.8-8.8 % of snaps show any level there). But the flow is tiny and never wins:

| taker SELL pressure on the underdog at ≤ 0.009, tl 2-30 | |
|---|---|
| prints / shares | 390 / 14,162 (**2,360 sh/day**, btc 1,710, hype 441) |
| price | 374 prints at 0.001, 11 at 0.002, 5 above |
| underdog token wins | **0 of 390 prints, 0 of 14,162 shares** |

Sim (bid at `best_bid + 0.001` capped 0.0095, 50 sh/bar, ahead = 0): **195 bars, 2,741 sh at mean
0.0012, 0 win events, −$3.38 / 6 d.** Break-even needs a 0.12 % flip rate on a pool worth ~$3/day of
stake — even at the favourite's observed 0.4 % late loss rate the ceiling is ≈ +$2/day. **Dead by
capacity; report events, not t-stats.**

## 4. Lead 3 — terminal re-score of the rebate-farm's two "not refuted" cells (`a5_rescore.py`)

| cell | half-spread | **drift** | adverse | rebate | published-style | **TERMINAL** | days + |
|---|---|---|---|---|---|---|---|
| (a) §7 two-sided touch, q .45-.60, spread ≤2c, first 60 s, LAT .15 | +0.549 | **−4.529** | −0.771 | +0.346 | +0.124 | **−4.404 ± 0.717** | **0/6** |
| (a) same, LAT .20 | +0.549 | −4.574 | −0.768 | +0.346 | +0.127 | −4.447 ± 0.718 | 0/6 |
| (b) cheap band .04-.15, tl 40-270 | +0.856 | **−2.224** | −0.911 | +0.112 | +0.057 | **−2.228 ± 0.444** | **0/6** |
| (b) .04-.08 | +0.906 | −1.770 | −0.389 | +0.076 | +0.593 | −1.247 ± 0.441 | 1/6 |
| (b) .08-.15 | +0.811 | −2.639 | −1.389 | +0.145 | −0.433 | −3.125 ± 0.591 | 0/6 |

Both "survivors" of `strat-rebate-farm-20260907` were artefacts of the drift-free metric (bug #37).
The first-60-seconds cell is the clearest case: the half-spread captured is small (0.55 c, the book
is wide and we join it) and the mid moves 4.5 c against us before we fill. **Nothing in the mid-bar
maker map survives on terminal PnL. The rebate-farm document has no open cell left.**

## 5. Lead 4 — mechanics census (`a6_mech.py`, `a8_exit.py`, `a9_postclose.py`)
- **Post-close tape (T+0 → resolution, 6 days):** 7,059 prints / 1.67 M sh. LOSER BUYs 1.31 M sh at
  0.001-0.01 (the 0.001 lottery buyers); WINNER SELLs 324 k sh at 0.99-0.999 (**22 k sh/day at
  0.98-0.99 and 32 k sh/day at 0.995-0.999**). A resting winner bid at `best + 0.001` would be hit
  by 100 % of that flow (**pool $217/day**) — but **$187 of it prints against a 0.99 best bid, i.e.
  coarse-tick bars where 0.991 is illegal**, and the fine-tick bars already have a 0.999 best bid
  (pool $30/day, and we would queue behind it). §56 stands, now from the tape.
- **0.999 exit for a tick-jump fill:** BUY prints at ≥ 0.999 after our fill exist in **0.8 %** of
  filled bars (0.5 % of shares exitable). Hold-to-settlement it is.
- **Minted-pair 0.999 ask:** BUY prints at ≥ 0.999 on the favourite are 2,134 sh/day (tl 0-30) and
  16,306 sh/day (tl 30-120, btc 12.9 k) and *always* win; loser BUYs post-close at ≤ 0.001 are
  157 k sh/day. Selling both legs of a $1 mint yields **0.999 + 0.001 = 1.000** — identity, no edge.
- **Venue rebate tier:** re-confirmed per-market 0.20 (parent §9b).

---

## 6. What remains true, and what a pilot would now be for
The book-side result survives every attack: in the last 30 s the favourite's sellers are benign, the
best-bid queue is 7,600 sh deep, and one tick of price priority converts a −0.09 c/sh join into a
+0.5-0.8 c/sh fill. **What kills it is the venue's clock.** Two things would reopen it:
1. **The flip lag shortens** (a venue change) — re-run `a12_tick.py` + `a13_tradeable.py`; the
   number to watch is *"flips before tl 30"* (now 13 %).
2. **Early-decided bars only**: a live arm restricted to markets whose `tick_size_change` has
   already arrived (subscribe to the event; place nothing before it) is worth **~$1-2/day at 50 sh**
   — a mechanism probe, not income. If run at all: 5 sh, all seven coins, G2 gate, and log every
   post-only rejection to measure the legality lag directly.

---

## Proposed README rows
| If considering… | Verdict | Why | File |
|---|---|---|---|
| **The 0.001-tick-jump maker (parent's 🟡 lane)** | ⛔ **INFEASIBLE on this venue's clock (2026-09-07, agent A)** | 16,212 raw `tick_size_change` events: the venue switches to the fine tick **~121 s after** the price first crosses 0.96; **74 % of flips are after close, only 13 % of decisive bars have it by tl 30**. Tradeable subset of the +$74/day sim = **34 bars, +$1.7/day**. Every other attack passed (98.1 % of prints at the best bid, 12 improvers in 3,905 bar-tokens, G2 persist-5s gate → 2 loss bars, all 7 coins positive) — the edge is in the book but 0.991 is an illegal price for 98.6 % of the fills | [strat-maker-hunt-r3 §2](strat-maker-hunt-r3-20260907.md) |
| **The rebate-farm's two "not refuted" cells (first-60s two-sided; .04-.15 band)** | ⛔ **both −2 to −4.4 c/sh, 0/6 days on TERMINAL PnL** | drift −4.5 / −2.2 c/sh; published-style +0.12 / +0.06 were the metric, not the money | [strat-maker-hunt-r3 §4](strat-maker-hunt-r3-20260907.md) |
| **Underdog bid at 0.002 in the last 30 s (mirror lottery)** | ⛔ capacity | 2,360 sh/day of flow, 0 winning events in 390 prints; ceiling ≈ +$2/day | [§3](strat-maker-hunt-r3-20260907.md) |
| **Post-close winner bid / minted 0.999 ask / 0.999 exit** | ⛔ | $187 of the $217/day post-close pool is in coarse-tick bars; 0.999+0.001 = 1.000; ≥0.999 demand after a fill in 0.8 % of bars | [§5](strat-maker-hunt-r3-20260907.md) |

## Proposed bug-ledger entries
**Bug #39 (2026-09-07, agent A): a limit price must be LEGAL at the instant it is placed, and on
Polymarket legality is a lagged venue state.** The 0.001 tick is switched per market by a
`tick_size_change` event that arrives ~121 s (p50) after the price first crosses 0.96 — 74 % of the
time after the bar has closed. A sim that quotes `best_bid + 0.001` whenever the price is above 0.96
places an order the venue rejects (`"invalid price, max: 0.99"`) in 98.6 % of its fills.
**Rules:** (1) every sim that uses a sub-cent price must gate on the recorded `tick_size_change`
timestamp for that market (`a12_tick.py` extracts them; `a13_tradeable.py` applies them); (2) the
snapshot book is *not* evidence of the regime — off-grid quotes appear a median 74 s after the price
crosses 0.96 and mostly post-close; (3) when a live lane got 0 fills against a sim that says 13 %
(§56 vs the tick-jump), assume the sim placed illegal orders before assuming queue physics.
**Bug #37 follow-through:** both cells the rebate-farm doc left open were drift artefacts
(−4.4 / −2.2 c/sh terminal); re-score any "not refuted" maker cell on terminal before citing it.
