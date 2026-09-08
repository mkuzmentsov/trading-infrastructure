# The stale-ask SWEEP: what it actually is, and why it cannot be predicted (2026-09-07)

Commissioned as round 2's primary target ("predict which displayed 0.99 asks are stale and about
to collapse in our favour"), and to settle the question
[strat-btc-live-ledger §9](strat-btc-live-ledger-20260907.md) left open: **is the 5× higher sweep
rate at tl≤12 causal (delaying produces sweeps) or selection?** Superseded as the top priority by
the user's maker-only scope change mid-run; the results below were already complete.
Working dir `scratchpad/pred2/` (`led.py`, `val3.py`, `dis*.py`, `haz.py`, `fitA*.py`, `paired.py`).

**Answer in one line: a "sweep" is not a future event to predict — it is the bot's own book being
STALE at the fire instant, and a fresh 10 Hz book shows the collapsed ask *already there*.
And delaying the fire does NOT manufacture sweeps, so §9's unresolved term resolves AGAINST the
fire-window shift.**

---

## 1. ⭐⭐ MECHANISM — the sweep is visible at the decision instant, in a fresh book

692 current-era live fills fall inside the mrec window (09-01→09-06); **443** have a `snapcur`
row within 0.3 s of the order (10 Hz maintained book, `evage` p50 **0.02 s**, p99 0.36 s).

| | non-sweep fills (n = 426) | **sweep fills (n = 17)** |
|---|---|---|
| fresh ask ≤ 0.95 × the bot's `seen_ask` | **0 / 426 (0.0 %)** | **13 / 17 (76.5 %)** |
| fresh ask strictly below `seen_ask` | — | **17 / 17 (100 %)** |

The fresh book predicts the realised fill price far better than the bot's own view:

| | vs the bot's `seen_ask` | vs the fresh 10 Hz ask |
|---|---|---|
| MAE of `avg_px` | 0.89 c | **0.51 c** |
| correlation with `avg_px` | 0.873 | **0.972** |
| P(fill above the quoted price) | 23.3 % | **7.7 %** |

Worked cases (fresh ask at the order instant → realised fill): bnb 0.99→**0.26** (filled 0.238),
eth 0.97→0.76 (0.799), sol 0.98→0.95 (0.930), btc 0.99→0.90 (0.890). On the event-stream data the
collapsed state had already existed for a median **0.33 s** (range 0.19-11.4 s) before we fired.

⇒ **There is no prediction problem here. There is a freshness problem.** The bot fires on a price
that has already moved; the dollar-sized FAK then matches against the true book. Which also means
**the sweep is already fully harvested by the existing mechanism** — a $-sized marketable order
with a limit at the stale price automatically buys more shares when the true book is cheaper.
Nothing is left on the table except *clip size* (§5 of the live ledger).

## 2. ⛔ Taking dislocations DELIBERATELY is not +EV at scale

Full population from the 10 Hz book: 2.5 M fresh favourite-side rows, tl 3-30, `evage<1s`;
a *dislocation* = fresh fav ask ≤ 0.95 × the same book's ask 1 s earlier. **1,241 events / 690
coin-bars; only 274 (22 %) tape-confirm** a real BUY print at ≤ that price within 0.4 s (house fill
model, $24 clip, size capped by displayed and tape size, fee 0.07·p(1−p)).

| population | fills | stake | pnl | ROI |
|---|---|---|---|---|
| all dislocations, blind | 274 | $3,366 | **−$128.32** | **−3.81 %** |
| + the live recon gate | 184 | $2,302 | +$18.96 | +0.82 % |
| gate + tl 3-20, prior ask ≥ 0.98 | 14 | $186 | +$18.62 | +10.02 % (**0 losses**) |

The last cell reproduces the live cell's *shape* (14 fills, zero losses) at **one seventh of its
ROI**. Blind dislocation-hunting is negative; the deliberate version of the sweep is not a trade.

## 3. ⚠️ The live sweep P&L is FIVE FILLS

| | current era, 7 coins |
|---|---|
| all 59 sweeps | +$136.15, ROI +17.4 %, **bootstrap 95 % CI [−7.3 %, +46.2 %]** |
| 0.99-origin (n = 14) | +$136.95, ROI +68.8 %, CI **[+12.4 %, +148.9 %]**, median fill **+$1.71** |
| largest single fill | **55.9 %** of all sweep profit |
| top 5 fills | **132.6 %** of all sweep profit (the other 54 are net negative) |
| fleet ex-top-5-sweeps | **+$40.04** of +$220.53 → **$4.96/day** vs $12.97/day |
| 0 losses in 14 | Jeffreys 95 % upper loss rate **12.6 %**, not 0 |

Sweep P&L by day is **negative on 6 of 16 days** (−$32.5 … +$87.5). ⇒ "sweeps are 61.7 % of fleet
profit" is true and **"the fleet's three weeks of profit is five fills" is the same statement**.
No sizing decision should be made against a 5-event sample.

## 4. ⭐ The collapse ITSELF is predictable — the money is not

Target: does a **fresh** favourite ask ≥ 0.98 collapse ≥5 % within the next 5 s?
Panel = one row per coin-bar-second, `evage<1s`, tl 3-30: 10,294 rows, **413 positives (4.0 %)**.
Two configs only (`A1` logistic, `A2` HistGB, fixed specs, pooled 7 coins, coin dummies).

| | OOS AUC | top-decile rate | lift | feature-shuffle null (30 draws) |
|---|---|---|---|---|
| A1 logistic | **0.7011** | 11.2 % vs 4.1 % base | **2.71×** | AUC 0.5024 ± 0.0186 → **z = +10.7** |
| A2 HistGB | 0.6770 | 11.2 % | 2.71× | AUC 0.5025 ± 0.0237 → **z = +7.4** |
| A1 walk-forward (expanding, daily refit) | **0.693** over 8,204 rows | — | — | 4/4 days 0.62-0.77 |
| bar level (does a bar contain a collapse) | **0.847** | 18.8 % vs 8.3 % | 2.3× | — |

Signs are mechanical and sensible: recent traded volume on the favourite (+), buying pressure on
the *opposite* token (+, the `ua ≡ 1−db` identity), recon margin |est| (−), top-2 ask depth (−).
**This is a genuine, well-powered positive — the first in two rounds of predictor hunting.**

**And it is worth nothing.** The only causal use is "delay the fire and take the collapse":

| score quintile | WAIT-minus-NOW, 4 OOS days |
|---|---|
| 0 / 1 / 2 / 3 / 4 | −$2.91 / −$5.54 / +$5.51 / +$12.06 / +$3.85 |
| **all 762 decision bars** | **+$12.96, bootstrap SE $12.37, z = +1.05** |

Not significant, and not monotone in the score. A model that ranks collapses at 2.7× lift moves
$3/day with an SE of the same size, because a captured collapse is worth a few dollars and the
capture rate is a few per cent.

## 5. ⭐⭐ §9's OPEN QUESTION, ANSWERED: delaying does NOT manufacture sweeps

Two independent routes, both well powered:

**(a) Unconditional hazard is flat in `tl`.** P(a fresh ≥0.98 favourite ask collapses ≥5 % within
5 s), one row per coin-bar-second: **4.2 % (tl 3-8), 5.0 % (8-12), 6.8 % (12-16), 5.6 % (16-20),
6.2 % (20-25), 5.0 % (25-30)**. No gradient — certainly not the 5× the live fill data shows.

**(b) The paired within-bar test** (the same construction §9 used). 761 bars carry a fireable
fresh ask at tl 16-20; 61.2 % still carry one at tl 12-16, 19.7 % at tl 3-8. Collapse ≥5 % below
*the tl-20 ask*, same bars:

| among bars that persist to… | collapse during tl 16-20 | collapse during the later window | paired diff |
|---|---|---|---|
| tl 12-16 (n = 466) | 21.24 % | 18.24 % | **−3.00 pp (t = −1.65)** |
| tl 3-8 (n = 150) | 40.67 % | 28.67 % | **−12.00 pp (t = −2.59)** |

**Waiting produces FEWER collapse opportunities, not more.** So the live "sweep rate is 5× higher
at tl≤12" is **selection** — bars that are still fireable late are the ones whose book was already
unstable — exactly the alternative §9 named. **The +21 c/fire sweep term that §9 needed to flip
the fire-window shift positive does not exist.** With §9's ordinary component at −0.187 c per
bar-opportunity, the shift is **mildly negative overall, and should not be deployed.**

## 6. Standing recommendations
1. **Stop calling the sweep an "option" the bot buys.** It is a measurement error in the bot's own
   book that occasionally pays. It is already captured; it cannot be aimed.
2. **Do not resize on it.** Five fills carry the entire result (§3), and the 0.99-origin cell's
   zero-loss record is consistent with a true loss rate up to 12.6 %.
3. **The fire-window shift (§8/§9) is now settled: do not deploy it.** Its ordinary component is
   −0.19 c/bar and its sweep component, measured directly here, is negative too.
4. If the sweep is ever to be *aimed*, the lever is book freshness at the fire instant (a second WS
   or a REST re-read before firing), not a predictor — but §2 says the resulting trades are ~0 EV,
   so the only thing freshness buys is knowing the price you are about to pay.
