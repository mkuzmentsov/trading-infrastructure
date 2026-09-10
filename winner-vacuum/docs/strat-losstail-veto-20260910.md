# The loss tail — bid-drop veto, re-derived on the LIVE FILL LEDGER and tested strictly OOS
**2026-09-10 (session ran into 09-11 UTC). Agent A. Nothing deployed, nothing committed, no bot config touched.**

Verdict up front: **SHIP** — but *not* the rule that was proposed. The bid-drop discriminator is
**confirmed out-of-sample and is stronger than anything previously claimed**, while two of the three
things §66 asserted about it are **REFUTED**:

| §66 claim | status |
|---|---|
| the favourite's own BID direction splits a cheap ask into gift vs trap | ✅ **confirmed OOS** (blocked-set loss rate 43.8% vs 1.4% kept, bar-clustered t=+3.41, permutation p<0.0002) |
| the cell is *also* about a THIN estimate (0.05–0.06 bps over threshold) | ⛔ **REFUTED**. With the bid drop in the model, estimate-thinness carries **t=+0.83 (all) / −0.85 (OOS)**, and inside the cheap band its loss rate is 26.5% vs 23.3% — i.e. nothing. This is the §37 mistake in miniature and it should be dropped from the story. |
| veto on the bid drop alone (`d<=−0.30/6s`, or `dB20<=−0.03`) | ⛔ **REFUTED as a standalone gate.** Un-conditioned it deletes the ≥0.90 bid-drop class, which is **83 fills, +$46.87, containing both era-scale sweep windfalls (+$76.14)**. The veto must be conditioned on the *displayed* ask. |

---

## 0. Why this pass can say something the previous six could not

**I did not use a replay.** I pulled the fleet's own `PF_TE_WHALE_ORDER` ledger from all seven live
pods (read-only, one `kubectl exec` each — the [[btc-live-fill-ledger]] method), joined it to
`res.parquet`, and attached the favourite's **own best-bid history** from the mrec 10Hz tape at the
exact fire timestamp. That gives **1,057 real fills, 34 real losses, 09-01→09-10**, with a real fill
price and a real outcome on every row.

Ground-truth check — my per-day net vs the RESEARCH-LOG day closes:

| day | log close (bars-losses) | this ledger (fills, losses) |
|---|---|---|
| 09-05 | +$29.99 (123-2) | +$26.27 (125, 2) |
| 09-06 | +$129.02 (120-2) | +$123.19 (122, 2) |
| 09-07 | +$31.32 (131-2) | +$28.32 (132, 2) |
| 09-08 | +$63.01 (158-2) | +$57.09 (161, 2) |
| 09-09 | **−$66.93 (95-7)** | **−$74.98 (99, 7)** |

Loss counts match exactly on every day. The ~$3–8/day gap is the taker fee: **the RESEARCH-LOG day
closes are GROSS** (confirmed independently by a parallel agent — $49.71 of fee over the window,
~24% of the headline). Everything in this document is **net of fee**.

⚠️ Corollary, and it matters for the whole program: **no fill model is used anywhere below.** The
loss-bar and $/day figures here are not "fill-model dependent" in the usual sense — they are the
fleet's actual money. (I did first rebuild the house replay cell; like the parallel agent I could
not reproduce the published +$34.94/312/22 benchmark — `calib.py` is not in the repo and my
re-implementation read −$158/611 bars/46 loss bars. That path was abandoned. `bug ledger`: the
published house-cell numbers are currently **unreproducible** and should not be quoted.)

---

## 1. Pre-registration (written before any result was looked at)

Fill cell: none — real fills. Hypotheses: (H1) bid drop over 5/6/10/20s predicts a losing clip;
(H2) estimate-thinness predicts it; (H3) in a joint bar-clustered model at most one survives.
Decision rule fixed in advance:
* **SHIP** iff OOS loss-bars/day falls ≥50%, OOS net $/day ≥ 0, and no leave-one-day-out fold
  flips the loss-count sign.
* **LOG-ONLY ARM** iff in-sample separation holds, OOS agrees in direction, but OOS has <8 losing clips.
* **REFUTED** iff OOS loss-rate lift <1.2× or the effect is carried by one day / one coin.

Full text: `winner-vacuum/tools/mrec/losstail/PREREG.md`. OOS = **09-08 → 09-10** (fit on ≤09-07). The original
[[bid-drop-veto]] derivation ended ~09-06, so 09-07 is semi-OOS and is reported inside the fit set
(the conservative choice).

---

## 2. The discriminator, full sample and strictly OOS

Loss rate of the flagged set vs the kept set, bar-clustered SEs (`(coin,ws)` clusters):

| rule | window | ALL n=1057 flagged / lossrate / t | IS ≤09-07 n=753 | **OOS 09-08..10 n=304** |
|---|---|---|---|---|
| `dB6 <= −0.03` | 6s abs | 128 / 16.4% vs 1.4% / **t=+4.54** | 95 / 12.6% / t=+3.17 | 33 / **27.3% vs 0.7%** / **t=+3.41** |
| `dB10 <= −0.03` | 10s abs | 124 / 14.5% / t=+4.00 | 91 / t=+2.71 | 33 / 24.2% / t=+3.09 |
| `dB20 <= −0.03` (vB) | 20s abs | 117 / 14.5% / t=+3.86 | 86 / t=+3.01 | 31 / 19.4% / t=+2.45 |
| `rB6 <= −0.30` (**the brief's rule**) | 6s rel | 45 / 31.1% / t=+4.21 | 32 / t=+3.29 | 13 / 38.5% / t=+2.69 |
| `rB10 <= −0.20` (vR) | 10s rel | 58 / 27.6% / t=+4.38 | 43 / t=+3.31 | 15 / 40.0% / t=+3.02 |
| **estimate thin** (`\|est\|−thr ≤ 0.6`) | — | 368 / 4.6% vs 2.5% / t=+1.73 | 261 / t=+1.98 | 107 / 3.7% vs 3.6% / **t=+0.08** |
| `dA6 <= −0.03` (our-side ASK fall) | 6s | 52 / 32.7% / t=+4.76 | | |

**The bid signal survives OOS on a window that did not exist when it was derived.** It is not a
one-day artefact: the OOS window contains the −$66.93 day *and* two normal days, and the split holds
across all three.

The **ask-fall** row is not a placebo — the favourite's own ask and bid move together
(`corr(dB6,dA6)=0.74`), and by the `ua ≡ 1−db` identity a collapsing book moves both. Jointly with
`cheap`, the two are tied full-sample (t 2.02 vs 2.09) but **OOS only the BID version survives**
(t 2.18 vs 0.70). Keep the bid form — §66/§67 said the same on replay data ("the same rule on the
ask drop gives only $20.55/day") and it now holds on real fills.

**Estimate-thinness does not survive at all.** Loss rate by `|est|` band over the whole sample:
0.5–1 bps 4.3% (22 losses), 1–2 bps 2.0%, 2–5 bps 2.6%, ≥5 bps 4.3% (n=23) — **non-monotone**.
The §66 narrative ("est thin ⇒ inside proxy noise ⇒ we're wrong") is a *description* of the losing
bars, not a *discriminator*: nearly all fires are thin, so thinness has no power.

---

## 3. ⭐ Which variable actually carries it — the §37 test

Linear probability model on `loss`, bar-clustered:

| | ALL (n=1057) | IS (753) | **OOS (304)** |
|---|---|---|---|
| `drop6` (dB6≤−0.03) | +0.054 (t 2.06) | +0.025 (t 1.13) | **+0.146 (t 1.82)** |
| `cheap` (seen_ask<0.90) | +0.140 (**t 2.73**) | +0.169 (t 2.56) | +0.073 (t 1.05) |
| `thin` | +0.009 (t 0.83) | +0.018 (t 1.44) | −0.016 (t −0.85) |
| `drop6 × cheap` | +0.154 (t 1.67) | +0.108 (t 1.00) | +0.243 (t 1.39) |
| `wide spread` (ask−bid≥0.10) | +0.017 (t 1.18) | — | −0.006 (t −0.20) |

Two variables carry the loss tail: **the displayed ask being cheap**, and **the favourite's bid
falling**. Thinness and spread add nothing once those are in. The 2×2 is the whole finding:

| | **no bid drop** | **bid drop (dB6≤−0.03)** |
|---|---|---|
| **ask ≥ 0.90** | 882 fills, 6 losses (0.7%), **+$124.27** | 83 fills, 5 losses (6.0%), **+$46.87** ← *contains both sweep windfalls, +$76.14* |
| **ask < 0.90** | 47 fills, 7 losses (14.9%), **+$24.48** ← *the "gift"* | **45 fills, 16 losses (35.6%), −$23.08** ← **the trap** |

OOS the same table reads: rich/no-drop 257 fills 1 loss +$45.68; rich/drop 20 fills 3 losses −$7.96;
cheap/no-drop 14 fills 1 loss +$5.10; **cheap/drop 13 fills 6 losses −$53.32.**

### Why the ask condition is load-bearing (the mechanism)
Fills that swept ≥20% below the displayed ask:

| | n | losses | $ |
|---|---|---|---|
| displayed ≥0.90, bid dropping | **2** | 0 | **+$76.14** |
| displayed <0.90, bid dropping | 10 | 7 | −$35.28 |
| displayed <0.90, no drop | 1 | 1 | −$24.74 |

A collapsing bid at a *rich* displayed ask is the free option the ledger already identified (sweeps
= 61.7% of fleet profit). A collapsing bid at a *cheap* displayed ask is an informed maker pulling
away from us. **Same book dynamic, opposite sign, split by the displayed price.** Vetoing on the bid
drop alone (the §66/§70 form, and the brief's `rB6≤−0.30`) throws away the first to catch the second.

---

## 4. The rule, chosen on the fit set alone and frozen

Grid: ask floor ∈ {0.80,0.85,0.90,0.95,0.98,none} × dB6 threshold ∈ {−0.01…−0.30, none} = 42 cells.
Objective, fixed before scoring: **maximise IS loss-bars removed subject to IS dollar cost ≤ $5/day.**
Argmax on the fit set (09-01→09-07) only:

```
VETO the clip when   seen_ask < 0.98
               AND ( fav_best_bid(now) − fav_best_bid(now−6s) <= −0.01
                     OR the favourite has no bid at all )
```

Note the **no-bid clause**: the single worst fill of the ten days — sol 09-09, 1,524 shares at
$0.0152 against a displayed 0.88, **−$24.74**, the flagship §66 bar — has *no favourite bid in the
book at the fire instant*. A `dB` rule that treats "no data" as "allow" misses exactly the worst
case. Treat a missing bid as a collapse.

| | fit set 09-01..07 (7d) | **OOS 09-08..10 (3d)** | full 10d |
|---|---|---|---|
| fills/day | 107.6 | 101.3 | 105.7 |
| **blocked/day** | 5.4 (5.0%) | 5.3 (5.3%) | 5.4 (5.1%) |
| blocked-set loss rate | 34.2% | **43.8%** vs 1.4% kept | 37.0% |
| losses blocked | 13 of 23 | **7 of 11** | 20 of 34 |
| **loss BARS/day** | 3.14 → **1.29** | **3.67 → 1.33** | 3.30 → **1.30** |
| forfeited wins | 25 = −$24.70/day | 9 = −$15.45/day | 34 = −$21.93/day |
| avoided losses | 13 = +$24.31/day | 7 = +$40.26/day | 20 = +$29.10/day |
| **net** | **−$0.39/day** | **+$24.82/day** | **+$7.17/day** |
| PnL | $183.06 → $180.34 | **−$10.52 → +$63.94** | $172.55 → $244.28 |

Permutation (flag shuffled within coin×day, 5,000 reps, OOS): **p < 0.0002**.

Threshold plateau — the rule is insensitive where it should be and sensitive where it must be:

| | dB6 ≤ −0.01 | −0.02 | −0.03 | −0.05 | −0.10 |
|---|---|---|---|---|---|
| ask<0.90 full $/day | +5.36 | +4.78 | +4.78 | +4.94 | +2.54 |
| ask<0.95 full $/day | +5.00 | +4.42 | +4.42 | +4.58 | +2.54 |
| ask<0.98 full $/day | **+7.17** | +6.60 | +6.60 | +6.87 | +4.84 |
| ask<0.99 full $/day | +8.23 | +7.85 | +7.93 | +8.65 | +7.14 |
| ask<**0.85** full $/day | −39.0 total | | −35.8 total | −34.2 total | |

Flat in the drop threshold across a 10× range; **the ask floor is what matters**, and dropping it to
0.85 flips the sign (the 0.85–0.90 slice holds ~$75 of losses). 0.98 is the fit-set argmax; 0.99 is
better on every axis but blocks 9.9 fills/day instead of 5.4 and is a much larger behavioural change
— not recommended without its own arm.

---

## 5. Leave-one-out (the buy-the-dip test)

**Leave-one-DAY-out**, frozen rule:

| dropped day | 09-01 | 09-02 | 09-03 | 09-04 | 09-05 | 09-06 | 09-07 | 09-08 | **09-09** | 09-10 |
|---|---|---|---|---|---|---|---|---|---|---|
| $/day | +7.97 | +12.51 | +1.89 | +4.83 | +9.60 | +12.02 | +7.29 | +10.27 | **−3.45** | +8.82 |
| loss-bars/day removed | 2.22 | 2.00 | 1.56 | 2.00 | 2.22 | 2.11 | 2.00 | 2.11 | **1.56** | 2.22 |

**Leave-one-COIN-out**, frozen rule: **all seven positive** — bnb +11.60, sol +11.20, btc +5.67,
xrp +4.84, doge +4.32, hype +3.73, eth +1.68 $/day; loss-bars removed 1.5–2.0 in every fold.

Worst fold is dropping **09-09** → **−$3.45/day**, and that is the honest headline on dollars: the
dollar gain is tail insurance, paid for on quiet days and collected on 09-09 (+$102.82 that day
alone). Per-day deltas are 4 positive / 4 negative / 2 flat.

The loss-bar reduction has **no bad fold at all**, by day or by coin.

---

## 6. Cost accounting — read this before quoting any number

Full sample: the rule **forfeits $21.93/day of winning PnL to avoid $29.10/day of losing PnL**.
Each side is ~3–4× the net. Day-block bootstrap (10 days, 20k reps):

| metric | mean | 95% CI | P(>0) |
|---|---|---|---|
| **$/day** | +7.17 | **[−16.55, +35.12]** | 0.689 |
| **loss-bars/day removed** | **+2.00** | **[+0.80, +3.40]** | **1.000** |

**The $/day figure is NOT established and must not be quoted as a target.** The loss-bar reduction
is established at every fill definition, every fold, every coin, and both sides of the OOS split.
This is the same conclusion the program reached in §67/§68/§72 — it survives contact with real fills.

Both tails are fat. The forfeited-win side is also concentrated: 34 blocked wins total +$219, of
which the top 3 are +$77.72 (spread over 3 days and 3 coins, so not a single-day artefact — but a
longer horizon could easily hand back the net). **We are subtracting one fat-tailed class from
another and the difference is noise; only the count moves reliably.**

Per coin, full sample: bnb (+$44 blocked, 0 losses) and sol (+$40 blocked, 2 losses) **lose money**
from the veto; btc, doge, eth, hype, xrp gain. Do not read a coin ranking into that — n is 0–5
losses per coin.

---

## 7. Rules that were tested and are dead

| candidate | result |
|---|---|
| `rB6 ≤ −0.30` (the brief's proposed rule) | weakest of all the bid forms: removes only 1.4 loss-bars/day (vs 2.0), OOS +$9.72/day. Superseded. |
| `dB20 ≤ −0.03` (vB) / `rB10 ≤ −0.20` (vR) | both work but both delete the ≥0.90 sweep class; full-sample $/day −5.25 and −1.54. Superseded by the ask-conditioned form. |
| **MIN_ASK 0.90** (the §72-4 competitor) | removes *more* loss bars (3.30→1.10/day) at a full-sample cost of −$0.14/day and OOS +$16.08/day, with **no ring buffer at all**. It is a genuine alternative — but LOO-day is negative in 5/10 folds (worst −$10.96) vs the veto's 1/10, and it blocks 9.2 fills/day vs 5.4. **Second choice, and much cheaper to try.** |
| trade-flow features `mf10/mf30`, `dp10/dp30` (panelflow2) | **null**: \|t\| ≤ 0.9 on the loss indicator, both full-sample and OOS. Closes the "is there a better discriminator in the flow panel" question. |
| coverage `cov<0.7`, `tl≥18`, ambient `vol` | null (\|t\| ≤ 1.1). |
| spread `ask−bid`, `bid/ask` ratio | real univariately (t=4.3) but **add nothing** jointly (t=1.18) — they are the cheap-ask and bid-drop variables in disguise. §72's "vR's vetoed set has median spread 0.45" is explained: spread is a collider, not a cause. |
| fill-price band 0.55–0.80 (parallel agent's finding) | **confirmed but not gateable as stated.** On the *fill* price 0.55–0.80 is −$39.69 / −9.1% ROI; on the **seen ask** — the only thing a live gate can key on — the same band is −$9.33 and blocking it is −$3.64/day full sample. The bad band on the seen ask is **0.55–0.90**, i.e. exactly `cheap`. The price signature and the bid-drop signature are the same cell viewed from two sides; the ask-conditioned veto captures it with 40% fewer blocked fills. |

---

## 8. ⚠️ Live-monitoring correction (unrelated to the veto, but do not miss it)

The handoff doc says: *"a loss at |est| ≥ 5bps never happened in 6 days and is a real anomaly —
escalate."* **It has now happened.** doge 09-10 20:00 UTC, `est_bps = +5.22`, displayed 0.99, filled
0.94, −$4.97, with `dB6 = −0.48`. Over the full sample the ≥5 bps band is 23 fills / 1 loss / +$3.58.
Retire the "0 losses at ≥5bps" escalation trigger — it was a 6-day small-sample fact, not a law.

---

## 9. Verdict — **SHIP**, with a named revert and two stated risks

The pre-registered SHIP bar was: OOS loss-bars/day −≥50% (**−64%**, 3.67→1.33 ✅), OOS net $/day ≥0
(**+$24.82** ✅), no LOO fold flipping the loss-count sign (**none of 17 folds** ✅), ≥8 OOS losing
clips (**11** ✅). It cleared on every axis, on real money, on a window that did not exist when the
rule was derived. I am honouring the pre-registration.

### The exact change

New gate in the whale loop, evaluated **before** the FAK is sent, on every clip (first and ladder):

```
PM_TE_BIDDROP_MODE      = log        # then "block"
PM_TE_BIDDROP_MAX_ASK   = 0.98       # apply only when seen_ask < this
PM_TE_BIDDROP_WIN_S     = 6
PM_TE_BIDDROP_TH        = -0.01      # favourite best bid, absolute fall over the window
PM_TE_BIDDROP_NOBID     = 1          # a missing/zero favourite bid counts as a collapse
```
Helm keys `pmTeBidDropMode / pmTeBidDropMaxAsk / pmTeBidDropWinS / pmTeBidDropTh / pmTeBidDropNoBid`
in all seven `winner-vacuum/chart/bots/*_vacmaker.yaml`. **Revert = `PM_TE_BIDDROP_MODE=log`**
(one env var, no image change). Deploy at a UTC-00:00 rollover so a restart cannot un-halt a coin
(§26). No other gate changes: `PM_TE_MIN_ASK` stays 0.55, the §58 first-clip skip stays, sizing stays.

Implementation requirements — these are not optional:
1. **The ring buffer must be the bot's own book history**, sampled on its existing 0.4s scan
   (~15 samples of the favourite's best bid). Do **not** add a new feed.
2. **`no bid` ⇒ veto** (see §4). The worst fill of the ten days is only caught by this clause.
3. Emit `PF_TE_BIDDROP` on every clip carrying `seen_ask, fav_bid, fav_bid_6s, dB6, dB20, rB10,
   est_bps, tl, decision` — **whether it blocks or not**, so the live arm keeps scoring itself.

### The two risks, stated plainly
* **Instrument gap.** I measured the bid on the *recorder's* 10Hz book. The bot's own view is
  demonstrably staler (on sweeps `seen_ask` was staler than the fresh book in 100% of cases —
  [[btc-live-fill-ledger]]). The live rule is therefore *not byte-identical* to the tested rule.
  This is exactly why requirement 3 exists: `PF_TE_BIDDROP` on the bot's own numbers is the check.
  If the user wants the 08-22 discipline applied strictly ("unknown must mean DELAY"), then run
  **`MODE=log` for one week first** — ~38 scored events/week, zero behaviour change, and it closes
  this gap directly. That is the only argument against shipping the blocking version now, and it is
  a good one.
* **We are deleting a fat-tailed class.** 34 winning fills worth +$219 over 10 days go with it. The
  net is a difference of two fat tails and is bootstrap-insignificant. **Judge the live result on
  loss-bars/day, never on PnL** — and expect roughly one visible "it blocked a good bar" per day.

### What to expect if it goes live
Clips −5%, ~5.4 blocked/day fleet-wide (≈0.8 per coin), losing bars **3.3 → 1.3/day**, and about
three blocked winners for every blocked loser. If blocked fires are not losing ~35–45% of the time
in the log stream, the rule is wrong and should come straight back off.

---

## 10. Reproduce

Scripts are in `winner-vacuum/tools/mrec/losstail/` (uncommitted, not deployed; pre-registration in `PREREG.md`):
`led.py` (parse the 7 pod ledgers) → `feat.py` (attach the favourite's bid history from
`snapcur.parquet` at the fire timestamp) → `an2.py`…`an10.py` (splits, LPM, LOO, bootstrap,
permutation). The pod pull is read-only:
`kubectl exec -n every-tick-single deploy/<coin>-vacmaker-every-tick-single -- sh -c 'zcat /app/logs/*.gz; cat /app/logs/logs-training-events.jsonl'`
(xrp's stream reset once — check the last timestamp per file before trusting it).
