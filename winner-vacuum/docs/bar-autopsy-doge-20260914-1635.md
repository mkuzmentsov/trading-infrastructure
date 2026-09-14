# Bar autopsy — `doge-updown-5m-1789403700` (2026-09-14 16:35–16:40 UTC)
**Built 2026-09-14 from the mrec v2 parquet pipeline. One bar. Nothing deployed, no bot config touched.**

User asked for a breakdown of this single market. It turned out to be a **live loss bar** (−$3.65,
doge's only loss of the day at the time of writing) and it is an unusually clean specimen: a
spike-and-revert near-tie where the bot bought the **wrong side** at the **worst instant**. Three
things fall out, one of them a pipeline bug.

## 0. Data + how to reproduce

Hour `20260914-16` of `doge-mrec` / `doge-mrecev` / `doge-brec` was not yet drained when this ran —
pulled directly (`kubectl exec … cat /app/logs/raw/<f>`, gzip-verified) into
`every-tick-single/data/mrec/doge/`. Scoped parquet built with the committed pipeline
(`ev2pq.do_ev` / `ev2pq.do_snapmeta` / `snap2pq.do` over hours 15–16, then `recon.py`, `panel.py`).
`cl.parquet` is not produced by a committed script — it is `snapcur` deduped on `(coin, cl_ts)`.
Chainlink coverage on this bar is essentially perfect: **58/59 strike-window ticks, 59/59 final-window**.

Bot side: `PF_TE_EVAL` / `PF_TE_WHALE_DELAY` / `PF_TE_WHALE_ORDER` / `PF_TE_LIVE_SETTLE` /
`PF_TE_VERIFY` from `deploy/doge-vacmaker-every-tick-single`, grepped on the bar id. Per the
[[replay-fill-model]] rule, **every dollar figure below is the pod ledger, not a replay.**

## 1. The bar

| | |
|---|---|
| strike (TWAP-60 over `[ws−62, ws−3]`) | **0.084248760** |
| final (TWAP-60 over `[end−62, end−3]`) | **0.084243952** |
| margin | **−0.571 bps** → **DOWN** |
| `PF_TE_VERIFY` | `ok: true`, strike err **0.0 bps**, close err **0.0 bps** |
| taker prints | 42, 461.2 sh, $311.26 notional |
| taker-side aggregate | **−$47.73 net** (−$44.08 gross, $3.65 fees) — endgame alone −$50.27 |

A **near-tie** (|margin| 0.57 bps). Per [[binance-chainlink-divergence]] this is exactly the slice
where the label is fragile — except here it is not: our own Chainlink capture reconstructs the
settlement to 0.0 bps against the venue's own numbers.

## 2. The underlying — a spike that fully reverted inside the settlement window

Chainlink deviation from strike, by second (`tl` = seconds to close):

```
tl 30   −3.12 bps      ← quiet, DOWN
tl 27   +0.37          ← spike begins
tl 23   +3.75
tl 18   +5.22
tl 14   +6.22 bps      ← PEAK
tl 13   +3.45
tl 12   +0.64
tl  9   −0.54          ← fully given back
tl  4   −0.77
```

The **running** window mean never turned positive: −2.65 at tl 30 → −0.73 at tl 14 → −0.57 final.
A 6 bps spike in the last 16 seconds could not move a 60-second average across zero. **The bar was
DOWN the whole time on any honest reading.**

Binance (`brec` bookTicker, new since 09-13) leads Chainlink by ~2 s. ⚠️ **Read it at full
resolution — 1-second bucketing blurs this bar into nonsense.** Binance held **+6.68 bps** from
tl 19.7, stepped up to **+7.86** at tl 16.76, and then **collapsed to +0.74 bps inside ~100 ms**
(tl 14.13 → 14.02, through the levels 5.49 / 3.12 / 1.93 / 0.74). The **last Binance update at or
before the fire (tl 14.016) reads +0.741 bps** — one second earlier it still read +7.862.

⭐ So at the fire instant Binance had **already fully given the spike back**, and the PM book
collapsed in the *same* 10 Hz row. The market makers were tracking Binance; our bot was the only
participant still pricing off the stale Chainlink peak.

## 3. The book — one repricing step, not a drift

`ua ≡ 1−db` holds throughout ([[taker-side-adverse-selection]]). The favourite flipped twice:

| tl | UP bid/ask | DOWN ask | market says |
|---|---|---|---|
| 30 → 26 | 0.02 / 0.04 | 0.98 | DOWN, hard |
| 17 → 14.12 | 0.88–0.93 / 0.93–0.98 | **0.07–0.13** | UP, hard |
| **14.00** | **0.10 / 0.72** | **0.90** | ← **the step** |
| 13.5 → 11 | 0.03–0.06 / 0.08–0.42 | 0.94–0.97 | DOWN, hard |

The whole reversal is **one 10 Hz row**: at `tl 14.12` UP is 0.92/0.93, at `tl 14.00` it is 0.10/0.72.
The market makers repriced in a single step, and the cheap-DOWN quotes at 0.07–0.13 (the mirror of a
real resting UP bid of 10–25 sh at 0.87–0.93) never printed — no DOWN trade occurs between tl 26.0
and tl 13.0. ⚠️ Whether that was takeable is **not settled by this tape** ([[pool-shrink-watch]]:
tape-gate every availability statistic). `PM_TE_MIN_ASK=0.55` blocks that band by design anyway (§38).

Who paid: the big loser is **not us** — 36.67 sh of UP at 0.95 at tl 16.43 (−$34.96), plus 7.2 sh at
0.96 (−$6.96). The bar's $1.25 winner is the classic tl 6.9 sweep of 133.7 sh of DOWN at 0.99.

## 4. What the bot did, second by second

| t (tl) | event | |
|---|---|---|
| 29.9 | `PF_TE_WHALE_DELAY` | side DOWN, ask **0.98**, est −2.692 — **blocked by the §37 delay** (`WHALE_VOL_DELAY_VOL=0.01`, `TL=20` ⇒ always wait for tl≤20) |
| 27.8 | `PF_TE_EVAL` → `PF_TE_BET` | paper bet **DOWN @0.98**, 1.8 sh — settles **+$0.033** ✅ |
| **14.0** | `PF_TE_WHALE_ORDER` | **side UP**, `est_bps +0.504`, `seen_ask 0.72`, `req_px 0.73`, filled **5.069 sh @ 0.72**, $3.65 |
| settle | `PF_TE_LIVE_SETTLE` | won DOWN → **−$3.65** |

So the live money went to the **loser**, at the **single worst row of the bar**, while the paper
evaluator on the same pod had the side right the whole time.

### 4a. Why the estimate said UP — reproduced exactly

`whale_loop` uses `_estimate(ws,"H1")` → `rtds.window_mean(SYM, end−62, end−3)`, which
**forward-fills every unpublished second from the last value at or before it** — i.e. it projects
the newest Chainlink tick across the *rest of the window*.

At the fire the relay had ticks through `end−16` (2.0 s lag). Reconstructing that estimator from
`cl.parquet`:

| tail filled with | H1 |
|---|---|
| **Chainlink's last tick (+6.22 bps) — what it used** | **+0.504 bps** ✅ reproduces the logged value exactly (obs 47, tot 60) |
| Binance mid **at** the fire instant (+0.74 bps) | **−0.610 bps** |
| Binance mid **one second earlier** (+7.86 bps) | **+0.933 bps** ← worse |
| the tail that actually happened | **−0.541 bps** (truth = −0.571) |

`eff_thresh = THRESH + THRESH_SLOPE·max(0, tl − THRESH_ANCHOR)` = `0.5 + 0.035·max(0, 14−14)` =
**exactly 0.500**. It fired on **+0.504** — clearing the gate by **0.004 bps**, at the one `tl` where
the slope term is zero. One second either side it was blocked (+0.488 at tl 15 vs a 0.535 bar;
+0.069 at tl 13).

⭐ **The mechanism: H1's forward-fill is a "price stays here" extrapolation, and it is maximally
wrong exactly at the top of a spike.** 13 of the 60 window-seconds were being filled at a peak that
had already reverted on Binance. This is not relay lag in the usual sense — the bot's *delivered*
ticks were fine — it is the *projection* of the undelivered tail.

## 5. Three findings

### 5a. ⚠️ BUG #45 — `panel.py`'s `est_bps` is still NOT the live estimator (bug #44 half-fixed)

Yesterday's fix (b) made `panel.py` forward-fill *within the delivered range*. The live estimator
forward-fills **to `end−3` unconditionally**: `window_mean(lo, hi)` always has `total = hi−lo+1 = 60`.
`panel.py` instead truncates at the relay frontier — `b = min(end−3, cl_ts+1)` — so its denominator
is only the delivered span. **They are different estimators.** On this bar at tl 14, panel reads
**−0.901** where live read **+0.504**: panel does not see the fire at all.

Scope check on what is local (**doge, 09-14 hours 15–16 only, 21 bars, 378 rows at tl 3–20** — thin,
one coin, one regime, illustrative not conclusive):

* `|live − panel.est_bps|`: **median 0.386 bps, p90 1.21, max 1.95**
* **side disagreement 2.4% of rows**
* rows clearing a 0.5 bps gate: panel 378 @ 100.0% side-accuracy, live 357 @ 99.7%

Against a **0.5 bps** threshold a median 0.39 bps discrepancy is not a rounding error. Direction of
the bias: panel's truncation makes it **quieter and better** than the live signal — it structurally
cannot make the spike-extrapolation error, so **any gate scored on `panel.est_bps` is being scored on
a signal the bot does not have, and flatters it.** Fix = fill to `end−3` always, keeping `obs`/`cov`
on real ticks. This partially re-opens §hunt-20260914's "the fix is justified by FIDELITY not
accuracy" note — fidelity was not actually reached.

### 5b. ⭐ The bid-drop veto (SHIP verdict, still not deployed) blocks this fire

[[bid-drop-veto]] / `strat-losstail-veto-20260910` §9 shipped a rule that is still absent from the
pods (no `PM_TE_BIDDROP*` in the doge env). Evaluated on the recorder's 10 Hz book anchored on the
**actual fire row** (`tl 14.00`, the row whose UP ask is the logged `seen_ask 0.72`):

```
seen_ask 0.72 < PM_TE_BIDDROP_MAX_ASK 0.98    → in scope
dB6  = −0.420   (favourite UP bid 0.52 → 0.10)  ≤ TH −0.01   → BLOCK
dB10 = −0.030                                    ≤ TH −0.01   → BLOCK
dB20 = +0.080                                                 → allow
```

⚠️ **Anchor discipline matters more than the result.** Anchored one row earlier (`tl 14.12`, UP bid
0.92) `dB6 = +0.400` and the rule **allows** the fire. The collapse and the decision are ~120 ms
apart. This is the doc's own "instrument gap" risk made concrete: on the recorder's clock the veto
fires, and whether it fires on *the bot's* clock depends on a sub-tick alignment we cannot settle
offline. **This bar is an argument for requirement 3 (`PF_TE_BIDDROP` log-only on the bot's own
numbers), not for shipping the blocking version.** n=1 changes nothing about the SHIP verdict either
way.

### 5c. ⛔ The freshness lever has a named, mechanical form here — **and it was refuted the same day**

> ⛔⛔ **SUPERSEDED.** The substitution proposed below fires the **wrong side** on
> `bnb-updown-5m-1789384200`, a +$9.06 win. Dead — see
> [bar-autopsy-bnb-20260914-1110 §1](bar-autopsy-bnb-20260914-1110.md).


[[binance-chainlink-divergence]] leaves "Binance 0.14 s vs relay 2.21 s ⇒ decide ~2.07 s before the
field" as the remaining edge, with the caveat that the *race* benefit is unmeasurable offline. This
bar is a case where freshness is **not** a race — it is an **estimator input**: use the live Binance
deviation, rather than the stale Chainlink tick, for the *projected tail* of the window. That single
substitution takes this decision from **+0.504 (fires, loses $3.65)** to **−0.610 (no fire)** —
within 0.04 bps of the truth.

⚠️ **And it is knife-edge in the other direction**: the same substitution made *one second earlier*
reads **+0.933**, i.e. it would have fired harder. The lever is only worth anything at sub-second
freshness, which is exactly the regime a 1-second-bucketed backtest cannot see.

⚠️ Do **not** read this as a result. It is **one bar**, chosen *because* it lost, which is the
selection [[vacmaker-analytics-leads]] keeps warning about, and [[latency-ceiling-closed]] has
already priced the general version of "better nowcast" at **$0.67/day**. The specific claim worth
testing is narrower and was not in that ceiling: *only the forward-filled tail*, *only when the
Chainlink frontier disagrees with Binance by more than some margin*. Testable offline on the pod
ledger + `brec`, with no race assumption. **Not proposed for deployment.**

## 6. Footnote: the §37 delay cost this bar ~$3.74

Had the tl 29.9 fire been allowed (DOWN @0.98, 5 sh) it would have made ~**+$0.09**; the delay put
the fire into the flip and it made **−$3.65**. This is the §37 payoff asymmetry working *against*
us for once and is **not** evidence against the gate — memory's own rule is that at ~30:1 win/loss
**win count is useless** and single bars carry no information. Logged so nobody re-derives it as a
finding.

## 7. Reproduce

`scratchpad/build.py` (scoped `ev2pq`+`snap2pq` over doge hours 15–16) → `recon.py` → `panel.py`;
bot side is one `kubectl exec … grep 1789403700 /app/logs/logs-training-events.jsonl`.
