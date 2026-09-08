# Mid-band (20-80c) MAKER: the cost frontier, the break-even rewards subsidy, and readiness — 2026-09-08 (agent C)

**User mandate:** *"find a way to trade market maker at 40-60c (or at least somewhere 20-80c),
preferably around 50c, to farm rebates and get ready for rewards in future (like what happened in
August)."*

**Framing (agreed up front):** the mid-band maker is **not +EV** on this venue — measured again
here on terminal PnL, every one of 47 pre-registered cells is negative, 0-1 of 6 days positive.
So this document does not ask "does it make money"; it answers three things the mandate actually
needs: **(A) what does reward-eligible presence COST, per share and per resting share-second, and
which policy minimises it; (B) how big must a rewards pool be to pay for it; (C) what is the
least-bad thing to run now at ≤$1-2/day; (D) is the code ready.**

Data: mrec v2 pq build, 7 coins, 09-01→09-06, **9,833 bars**, real print tape. Harness
`winner-vacuum/tools/mrec/midband/mb.py` — event-driven, one resting order per side per bar,
queue-ahead at placement (bug #11), tape-size-capped (#28), `evage<1s` (#34), **terminal PnL
`win − q` + rebate with the 3-term decomposition (#37)**, bar-clustered SE, and **resting
share-seconds inside the reward band** (`|q − mid| ≤ 1.5c`, size ≥ 50, **and `tl ≤ 250` because
the Aug reward config attached ~50 s after the open** — see §B). 0.5 s scan, 0.2 s place latency.

---

## A. THE COST CURVE — 47 cells, all negative; cancel-on-touch-move is the only big lever

Pre-registered family: placement {join touch, 1 tick behind, improve 1 tick when spread ≥2c,
`edge05` = tick floor of mid−0.5c, `edge15` = tick floor of mid−1.5c} × mode {static hold 10 s,
cancel-on-touch-move} × size {20, 50, 100} × band {20-80, 40-60} × window {full 40-250, first
60 s, minute 2, mid, late} × sides {both, one, random}. Full table: `tools/mrec/midband/sweep_scored_all.csv`.

### A1. Placement × mode (50 sh/side, both sides, 1 fill/side/bar, tl 40-250, q 0.20-0.80)

| policy | filled sh/day | **$/day** | **c/share** | ± | half-spread | **drift** | adverse | rebate | pair rate | pair sum | days + |
|---|---|---|---|---|---|---|---|---|---|---|---|
| join / static | 67,110 | −4,500 | −6.71 | 0.19 | +1.25 | **−7.32** | −0.90 | +0.30 | 0.71 | 1.057 | 0/6 |
| **join / cancel** | 54,237 | **−1,370** | **−2.53** | 0.22 | +1.19 | **−3.06** | −0.95 | +0.31 | 0.69 | 1.026 | 0/6 |
| behind / static | 65,522 | −4,659 | −7.11 | 0.21 | +2.42 | −8.78 | −1.01 | +0.30 | 0.76 | 1.032 | 0/6 |
| behind / cancel | 46,154 | −1,618 | −3.51 | 0.28 | +2.35 | −4.66 | −1.49 | +0.31 | 0.70 | 1.009 | 0/6 |
| improve / static | 77,265 | −4,341 | −5.62 | 0.18 | +1.33 | −5.99 | −1.25 | +0.30 | 0.90 | 1.026 | 0/6 |
| improve / cancel | 56,025 | −1,405 | −2.51 | 0.25 | +1.64 | −2.78 | −1.67 | +0.31 | 0.85 | 0.998 | 0/6 |
| edge05 / static | 82,463 | −5,511 | −6.68 | 0.16 | +0.64 | −6.39 | −1.20 | +0.30 | 0.90 | 1.048 | 0/6 |
| edge05 / cancel | 72,317 | −2,252 | −3.12 | 0.17 | +0.65 | −2.51 | −1.56 | +0.31 | 0.90 | 1.022 | 0/6 |
| edge15 / static | 75,317 | −5,359 | −7.12 | 0.18 | +1.63 | −7.88 | −1.13 | +0.30 | 0.85 | 1.045 | 0/6 |
| edge15 / cancel | 60,038 | −2,136 | −3.56 | 0.23 | +1.65 | −3.68 | −1.83 | +0.31 | 0.84 | 1.017 | 0/6 |

**Where the cost is:** the **drift** term — the mid moving from placement to fill — is 2-3× the
adverse-selection term in every cell, and the half-spread never covers it. Cancelling whenever
the touch moves cuts the drift from −7.3 to −3.1 c/share and the bill from −$4,500 to −$1,370/day.
**The rebate is +0.30-0.35 c/share against a 2.5-7 c/share loss: 5-12 % of the hole.** "Farming
rebates" in this band nets −2.2 c/share at best.

Validity checks (README §4): static hold H 3 / 10 / 30 s → −4.5 / −6.7 / −8.9 c/sh (longer rest
= worse ✓); resting behind the touch is worse than joining (deeper fills lose more ✓); place
latency 0.1 / 0.2 / 0.4 s → −2.30 / −2.53 / −2.63 (delay-sensitive in the right direction ✓);
random-one-side placebo −3.59 vs two-sided −2.53 (the pair term is real and worth ~1 c/sh ✓);
40-60c band is worse than 20-80 at every placement (−3.44 vs −2.53 join/cancel ✓ matches
strat-maker-4060-pooled).

### A2. Window (join/cancel and edge15/static, 50 sh)

| window | join/cancel c/sh | $/day | edge15/static c/sh | $/day |
|---|---|---|---|---|
| **first 60 s (tl 240-300)** | **−1.23 ± 0.31** | **−521** | −5.00 | −2,585 |
| first 60 s ex first 4 s (240-296) | −1.59 | −626 | −4.49 | −2,054 |
| minute 2 (180-240) | −2.59 | −888 | −6.01 | −2,553 |
| mid (120-180) | −2.82 | −755 | −7.17 | −2,674 |
| late (40-120) | −3.30 | −776 | −9.10 | −3,441 |

The first minute is the cheapest place to be a maker (it replicates the rebate-farm doc's
gradient, now on terminal PnL — and it is still **negative, 0/6 days**). ⚠️ **But the first
minute earns no rewards**: the Aug config attached ~50 s after the open, so a tl 240-300 quote
scores for ≈10 s of its 60. Reward-eligible presence per $ is the metric that matters for the
mandate, and it inverts the ranking:

### A3. The frontier — cost per 1,000 reward-band share-seconds (50 sh, config lag applied)

| policy | $/day | in-band k share-s /day | **$ per k share-s** | filled sh/day |
|---|---|---|---|---|
| join / cancel, size 100, full window | −2,537 | 9,664 | **−0.262** | 90,515 |
| **edge05 / cancel, full window** | −2,252 | **7,473** | **−0.301** | 72,317 |
| join / cancel, full window | −1,370 | 4,391 | −0.312 | 54,237 |
| join / cancel, MAXFILL ∞ (re-quote after fill) | −5,843 | 6,069 | −0.963 | 214,151 |
| join / cancel, first 60 s | −521 | 456 | −1.142 | 42,566 |
| improve-only-into-spread ≥3c / cancel, first 60 s | −374 | 172 | −2.181 | 19,968 |
| edge15 / cancel, full window | −2,136 | 4,244 | −0.503 | 60,038 |

**Cheapest reward-eligible presence: `edge05/cancel` (0.5 c inside the band edge, cancel on touch
move) or `join/cancel` — ≈ $0.30 per 1,000 share-seconds in band.** Cheapest *per filled share*:
`join/cancel first 60 s` (−1.23 c) — but it buys almost no eligible presence. Re-quoting after a
fill (`MAXFILL ∞`) triples cost for +40 % presence: **never re-arm after a fill** (Aug's finding,
re-confirmed on terminal PnL).

Per-coin dispersion (warning only — replay coin ranking is r = −0.63 vs live): in the first-60s
join/cancel cell btc is −1.64 c/sh (−$305/day of the −$521) and thin-book doge/bnb/hype are
+0.7…+4.9 c/sh on small volume; per day 0/6 positive pooled.

---

## B. THE BREAK-EVEN SUBSIDY — "rewards must pay ≥ $X per coin per day"

### B1. Mechanics verified live 2026-09-08 (`tools/mrec/midband/rewards_monitor.py`)
All 8 coins' current 5m markets: `rewardsMinSize 50`, `rewardsMaxSpread 4.5` (per-bar field —
seen 0/1.5/4.5 in Aug; never hard-code it), **`clobRewards: None ⇒ daily rate $0`**,
`feeSchedule {rate 0.07, takerOnly, rebateRate 0.2}`, `orderPriceMinTickSize 0.01`,
`orderMinSize 5`. Two separate subsidies:
- **Maker rebate** = 20 % of the taker fee on OUR OWN fills = `0.2·0.07·q(1−q)` ≈ **0.35 c/share
  at 50c** (0.30 c/sh share-weighted in every cell above). It is a per-fill credit, not a pool.
- **Liquidity rewards** (the Aug program) = pool × our share of `Σ ((v−s)/v)²·size` (Q_min of the
  two sides, ≥50 sh orders, sampled ~1/min, current bar only, from ~50 s after open).

### B2. Our share of a pool (`rewshare.py`, field Q from the recorded top-3 ladders, 1/min samples, tl ≤ 250, mid 0.20-0.80)

| coin | field Q_min (v=1.5c) | share, 50sh `edge05` | share, `join` | v=4.5c: `edge05` / `join` |
|---|---|---|---|---|
| btc | 32.8 | **0.57** | 0.53 | 0.29 / 0.27 |
| eth | 0.9 | 0.98 | 0.81 | 0.89 / 0.80 |
| sol | 0.3 | 0.99 | 0.65 | 0.93 / 0.82 |
| xrp | 0.1 | 1.00 | 0.50 | 0.97 / 0.80 |
| bnb / doge / hype | 0.1-0.2 | 0.99-1.00 | 0.16-0.26 | 0.93-0.96 / 0.50-0.66 |

**Today's alt books have essentially no ≥50-share in-band size**: a single 50 sh two-sided quote
would take ~all of an alt pool and half of btc's. (`join` scores badly on alts because the touch
is often >1.5 c from mid; `edge15` scores ≈0 — the far edge of the band has weight ((v−s)/v)² → 0.)
⚠️ This is the *pre-program* field. In Aug the live rewfarm measured **~$29/day captured of btc's
$10k pool** and **$60-130/day per alt** — the field arrived with the money. Both anchors are
reported below.

### B3. Break-even pool (`breakeven.py`; reward = pool × share × presence, presence = in-band share-seconds ÷ a 50 sh two-sided quote resting the whole eligible window)

| policy (50 sh, 7 coins) | cost $/day | presence | Aug-2026 pools, **today's field** | **net** | **break-even pool / coin / day** | Aug-measured capture (realistic) | net |
|---|---|---|---|---|---|---|---|
| **edge05 / cancel** | 2,252 | 0.217 | $3,030 (v 1.5) / $2,324 (v 4.5) | **+$777 / +$71** | **$1,591 / $1,752** | ≈ $30 + 6×$100 ≈ $630 | **−$1,600** |
| join / cancel | 1,370 | 0.128 | $1,175 / $1,086 | −$195 / −$284 | $3,456 / $2,470 | ≈ $400 | −$970 |
| join / cancel, size 100 | 2,537 | 0.281 | $2,586 / $2,391 | +$50 / −$145 | $2,907 / $2,077 | — | — |
| join / cancel, first 60 s | 521 | 0.013 | $122 / $113 | −$399 | $12,652 | ≈ $0 | −$521 |
| improve≥3c / cancel, first 60 s | 374 | 0.005 | $46 | −$328 | $24,148 | ≈ $0 | −$374 |

**The go/no-go trigger:** run the mid-band maker only when a rewards program pays **≥ ~$1,600-
1,800 per coin per day** (uniform across coins) **and the in-band field is as empty as it is
today**; if the field returns to its August thickness (btc capture ~$29/day), no pool size that
has ever been offered on this venue breaks even. The Aug program's alt pools were $833-1,667 —
**just below** the optimistic break-even and far below the realistic one. **Rewards pay only
in the window (tl ≤ 250) where the maker cost is highest**, which is why the first-minute cell
cannot be the rewards vehicle.

---

## C. THE LEAST-BAD LIVE CONFIG — and why "≤ $1-2/day" means ~one quoted bar per hour

Cost per filled share is 1.2-2.5 c in the best cells, so a $1.50/day budget buys **~60-120 filled
shares/day**. Two honest options:

| option | config | c/share | expected cost at budget | reward-eligible? | what it buys |
|---|---|---|---|---|---|
| **C1 plumbing-only** | `improve3/cancel first60`, size 20, ONE coin, 4-6 bars/day | −1.66 ± 0.54 | ≈ −$1.5/day (≈90 sh) | **no** (first minute, 20 sh) | live fill/cancel physics, rebate receipt (~$0.30/day) |
| **C2 rewards-shaped** | `edge05/cancel`, size 50, both sides, ONE coin, 1-2 bars/hour, tl 40-250 | −3.12 ± 0.17 | ≈ −$2/day (≈65 sh) | yes, ~1 % presence | exercises the exact policy that flips first if a pool returns |

Checked on the way (terminal PnL, all 7 coins × all bars, 50 sh): **improve-into-a-wide-spread**
(quote 1 tick inside only when spread ≥3c, so we are alone at our level — the tick-jump analogue)
= **−2.99 ± 0.31 c/sh full window, −1.88 ± 0.65 first 60 s** — better than joining at the touch
in the same window on pairs (pair sum **0.976-0.989**, 56-65 % of pairs < $1) but the single legs
still lose; 1/6 days positive. **First 60 s on terminal PnL: −1.23 c/sh join/cancel, 0/6 days** —
the drift-free metric's "only positive cell" is −$521/day when the drift is counted. The 40-60c
sub-band is worse than 20-80 in every configuration (−1.91 vs −1.23 first-60s join/cancel).

**Recommendation for the mandate:** do not run C2 for rebates (it nets −2.8 c/share after the
rebate). If the user wants the plumbing warm for a future program, **C1 at one coin, or nothing,
plus the monitor** — and re-run `sweep2.py`/`breakeven.py` the day `clobRewards` reappears, with
the pool size it announces.

---

## D. READINESS AUDIT — `openmm/` vs the frontier policy

`openmm/src/openmm.py` (591 lines) + shared `engine/clob.py`, one deploy yaml (`btc_openmm.yaml`),
own PM account (vault 0xd632c1e1…), paper/dry-run gated. Findings:

| item | state | gap for the frontier policy |
|---|---|---|
| post-only GTC, reject-on-cross | ✅ `place_limit_order(... post_only=True)`, rejection counted (`PF_OM_REJECT`) | — |
| tick size | ✅ `clob.py` passes `tick_size` from the WS-tracked `tick_size_change` and refreshes the client's stale cache | quoting logic itself hard-codes `round(bid, 2)` — fine in the mid band |
| cancel-on-touch-move | ✅ "re-pin" when the touch moves, `MIN_REST 1.0 s`, `COOLDOWN 0.5 s` | matches `join/cancel`; `edge05` needs a mid-relative price (not built — 1 line) |
| one fill per side per bar, pair ceiling 0.985, inventory cap | ✅ | pair ceiling not in the sim; keep it (Aug: it is what made pairs pay) |
| fee / rebate | ✅ `rebates_loop` polls `clob/rebates/current` daily | — |
| **rewards fields** | ❌ nothing reads `clobRewards` / `rewardsMinSize` / `rewardsMaxSpread` | **`tools/mrec/midband/rewards_monitor.py` (new, not deployed)** — exit 2 when a 5m market carries a daily rate |
| **size** | ❌ `PM_OM_SIZE=5` ($2.50) — **earns zero rewards (min 50 sh)** and 10× under the sim | must be 50 per side to score; capital ≈ $50/coin/bar at 50c |
| window | `TL_LO 240 / TL_HI 297` = **first minute only** | rewards-eligible window is tl ≤ 250 — the opposite window |
| **gates** | `PM_OM_IMB 0.2` (top-of-book imbalance), `PM_OM_FV`, `PM_OM_PULL_BPS` | **the `imb0` gate was shown to make fills WORSE once the queue is modelled** (strat-maker-4060-pooled §3: −7.03 → −9.92 c/sh) — set `PM_OM_IMB=-1`; the spot-velocity pull gate was refuted in Aug (43/48 loser singles at flat velocity) — set `PM_OM_PULL_BPS` high |
| halts | ✅ sticky UTC-day halt at `LIVE_MAX_DAILY_LOSS_USD` (yaml: $10) | set to the budget: $2-3 |
| reconciliation | 5 live bugs fixed in Aug ("every local counter is a cache"); `LIVE_RECONCILE_SECS 30` REST fallback | untested since 08-22 — run one paper day before any live order |
| coins | only `btc_openmm.yaml` | btc is the **worst** coin in every first-minute cell here (thick book: joins fill only on sweeps); a pilot coin cannot be chosen from the replay (r = −0.63) — pick by capital/ops, not by this table |

Concrete change list to run C1/C2: (1) `pmOmSize 50` (C2) or `20` (C1); (2) `pmOmTlLo/TlHi` to the
chosen window; (3) `pmOmImb -1`, `pmOmPullBps 999`; (4) add `PM_OM_PLACE=edge05` (mid − 0.5 c
floored to tick) as an alternative to touch-join — ~15 lines in `_tick`; (5) a bar-rate limiter
(`PM_OM_BARS_PER_HOUR`) so the budget binds — not present; (6) `liveMaxDailyLossUsd 3`;
(7) deploy the rewards monitor as a cron or sidecar and gate quoting on its exit code if the goal
is "quote only when rewards are on".

---

## Files
`winner-vacuum/tools/mrec/midband/`: `mb.py` (harness), `sweep2.py` / `sweep3.py` (the family),
`report.py` (scoring, 3-term decomposition, LOO, share-seconds), `rewshare.py` (pool share),
`breakeven.py` (subsidy), `rewards_monitor.py` (venue poll), and the result tables
`sweep_scored_all.csv`, `rewshare.csv`, `breakeven.csv`. Note: the first sweep was OOM-killed
running 7 workers alongside two other agents — `sweep2.py` loads each coin once and runs all
policies on it with 2 workers.

## Proposed README rows
| **A MAKER in the 20-80c / 40-60c band "to farm rebates and be ready for rewards"** | ⛔ **NEGATIVE in all 47 pre-registered cells on terminal PnL (2026-09-08); the rebate is 5-12 % of the hole** | join/cancel −2.53 c/sh (−$1,370/day @50sh×7 coins), join/static −6.71; **drift is 2-3× adverse selection** and cancel-on-touch-move is the only big lever (−7.3 → −3.1 c/sh drift). First 60 s is cheapest per share (−1.23, 0/6 days) but earns ~no rewards (config attaches at ~tl 250). Cheapest reward-eligible presence: `edge05/cancel` ≈ **$0.30 per 1,000 in-band share-seconds**. **Go/no-go: a pool ≥ ~$1,600-1,800/coin/day with today's empty field**; at Aug's measured capture no pool ever offered breaks even. `openmm` needs size 50 (now 5 = zero rewards), the imb/pull gates off, and reads no rewards fields — monitor script written, not deployed | [strat-midband-mm-rewards-20260907](strat-midband-mm-rewards-20260907.md) |

## Proposed bug-ledger entry
**#39 (2026-09-08, agent C): reward-eligible presence must apply the config lag.** The Aug rewards
config attached ~50 s after bar open (rewfarm §1), so share-seconds at tl > 250 score nothing.
Scoring the first-60s cell without the lag overstated its reward presence **7×** (3,226k → 456k
share-s/day) and its break-even pool by the same factor. Rule: any "presence" statistic for a
rewards program is gated on the program's own attach time, per market, read from the venue.
