# Does Binance predict the unobserved tail of the Chainlink TWAP?
**2026-09-14/15. 30 hours (09-13 14:00 → 09-14 20:00 UTC), 6 coins, 2,006 settled bars, 54,391
decision-rows. Nothing deployed, existing strategy untouched.**

Answer: **yes, mechanically and robustly — and no, it is not a tradeable new strategy at the prices
on offer.** Both halves matter.

## 0. ⛔⛔ FIRST: yesterday's refutation of this lever is VOID — it tested a mis-specification

On 09-14 I "refuted" the tail-freshness lever on `bnb-updown-5m-1789384200` and wrote it up as dead
([[bar-autopsy-bnb]] §1, README row, commit `664ff6d`). **That test filled the tail with Binance's
ABSOLUTE LEVEL deviation.** Binance's mid sits at a systematic offset from the Chainlink aggregate —
**+4.71 bps on average across this window** — so that substitution injects a 4.7 bps bias and flips
signs for free. It was a strawman.

The correct feature is **Binance's MOVE since the last Chainlink tick**, `bin_move = bin(now) −
bin(T)`, in which the offset cancels by construction. On the two bars I argued from:

| | Binance LEVEL | Binance at last tick | **bin_move** | H1 | H1+bin_move | yesterday (level) | truth |
|---|---|---|---|---|---|---|---|
| bnb (+$9.06 win) | +4.772 | +4.217 | **+0.555** | −0.538 | **−0.408** | +0.614 ❌ | −0.227 |
| btc (−$20.80 loss) | +6.926 | +2.573 | **+4.353** | −1.947 | **−0.568** | +0.851 ❌ | +0.049 |

On bnb the "divergence" I built the refutation on was **already there before the last tick** — the
real move was +0.56 bps, not +4.8. The correct estimator keeps the right side. ⚠️ **Do not now
over-correct in the other direction**: those are still two bars. The evidence below is the evidence.

## 1. The mechanism: Chainlink follows Binance one-for-one

Target `tail_err` = (mean of the *unobserved* tail ticks) − (last observed tick), i.e. exactly the
quantity the live estimator assumes is **zero** when it forward-fills. Feature `bin_move`.

| | |
|---|---|
| corr(`bin_move`, `tail_err`) | **+0.3996** (n=54,391) |
| **OLS slope** | **1.003** (intercept +0.003) |
| R² | 0.160 |

Slope 1.00 means: *if Binance has moved X bps since Chainlink last printed, the tail lands X bps
above the last tick.* The bucket table is monotone and on the diagonal (−4.88→−4.29, −1.63→−1.60,
+1.64→+1.74, +4.78→+4.70). Per coin the slope is **0.94–1.16** (all 6); per day **0.96 / 1.01**.
This is not fitted — it is Chainlink being a lagged aggregate of spot.

## 2. It measurably improves the estimator

`H1' = H1 + bin_move · ntail/60`.

* Mean |error| vs the realised margin: **0.3076 → 0.2862 bps (−7.0%)**.
* Side accuracy: +0.0 to +0.25 pp by `tl` (H1 is already 97.7–99.7%, so there is little room).
* **Where the two disagree** — 96 rows on 64 bars — **H1 is right 29.2%, H1' is right 70.8%**, and
  it is monotone in conviction: 61% / 73% / 85% / **100% (8/8)** as |H1'| rises through 0.25 / 0.5 /
  1.0 / 2.0 bps.

## 3. ⛔ But there is no new taker lane. The market prices it.

Decisive rows (|H1'| ≥ the live gate) with a takeable ask ≤0.99: **2,194 rows on 334 bars.**

| ask band | n | accuracy | ask (market) | edge | net c/share | H1-only |
|---|---|---|---|---|---|---|
| 0.02–0.55 | 29 | 51.7% | 0.331 | +18.6pp | +17.18 | +6.83 |
| 0.55–0.75 | 30 | 43.3% | 0.658 | −22.5pp | −24.01 | −24.01 |
| 0.75–0.90 | 92 | 84.8% | 0.847 | +0.0pp | −0.85 | −4.11 |
| 0.90–0.95 | 117 | 94.9% | 0.926 | +2.2pp | **+1.76** | +0.05 |
| 0.95–0.98 | 229 | 95.6% | 0.962 | −0.6pp | −0.81 | −1.25 |
| **0.98–0.99** | **1,697** | **98.76%** | **0.987** | **+0.05pp** | −0.04 | −0.10 |
| **ALL** | **2,194** | | | | **−0.157** | **−0.613** |

⭐ **The 0.98–0.99 band is 77% of the flow and is priced to five hundredths of a percentage point.**
That is an extremely efficient market and it is the whole reason this does not become a strategy.

⭐ **Binance is worth +0.456 c/share** (−0.613 → −0.157). Real, and roughly half the gap to zero —
but it does not cross zero.

The only positive band, **0.90–0.95 (+1.76 c/sh)**, survives ex-best/ex-worst (+1.69/+2.59) and both
days — but is **4 coins positive, 2 negative** (sol −7.2, eth −4.4) at n=117. **Not callable.**

### Lanes checked and closed
* **"Bars the bot skips that Binance makes decisive"** (|H1|<gate, |H1'|≥gate): 65 bars, side
  accuracy 90.9% — but the average ask is 0.910, so it is **−0.46 c/share**. Signal real, priced.
  (Control: H1's side on the same rows is 78.8% / −12.58 c/sh, so the signal is genuinely Binance's.)
* **TWAP-damping over-reaction** (does the book price a late spot move as if it were an endpoint
  move, when it is only worth `ntail/60` of it?): no coherent pattern — edge is +7.0pp at
  |bin_move|>2 early but −7.0pp at 1–2 early, n=21–54 per cell, signs flip. **No.**

## 4. Verdict

**No deployable new strategy from 30 hours.** What exists is a *better estimator*, and its value
lands on flow we already have — which is out of scope by instruction, and is anyway the thing to
be careful about.

**The binding constraint is tape, and it is self-solving.** `brec` started 09-13 17:40 and
accumulates ~1.5 GB/day. This analysis is 30 hours; in a week it is 5×, and the 0.90–0.95 cell and
the sub-0.55 cell (+17 c/sh, n=29) both become answerable. **Re-run this exact script then** rather
than concluding from n=117.

## 5. Reproduce

`scratchpad/bx/{build.py,panel.py}` — `build.py` extracts continuous Chainlink ticks (all SNAP
roles), RES, the cur-role book and the Binance `bookTicker` parquets; `panel.py` emits one row per
(coin, bar, tl∈[3,30]) with the relay frontier respected (bug #25).
⚠️ **Use `bin_move`, never the Binance level.** The level carries a +4.71 bps offset that will
manufacture whatever result you want.
