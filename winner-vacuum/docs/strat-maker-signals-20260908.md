# Signals as continuous quote MODULATORS for a 30-70c maker (skew / width / fair-value) + terminal re-score of prior conditioning verdicts — 2026-09-08 (agent F)

**User mandate:** *"based on the volume, volatility, ob data, prices, twap and binance prices trade frequently … It may
need to trade also with makers orders as well to negate risks … Previous investigations may need to be re-checked."*
Only 5m crypto up/down. Written INCREMENTALLY (§0 pre-registration first, results appended as they land).

⚠️ **Data note.** The 09-06 parquet build (`b78fafe5/pq`) that every prior doc ran on was deleted with its session
scratchpad. This doc runs on a FRESH build of the same pipeline (`tools/mrec/{ev2pq,snap2pq,recon,panel}.py`, `cl.parquet`
= dedup of snapshot `cl/cl_ts`) over the raw mrec now on disk: **09-01 20:00 → 09-08 06:00 UTC** (+1.4 days vs prior docs).
Positive control: `verify.py` must reproduce the rebate-farm headline components (+0.87 / −1.56 / +0.25) before anything
else is quoted. Scripts: `winner-vacuum/tools/mrec/signals/`.

---

## 0. PRE-REGISTRATION (written before any result)

### 0.1 Baseline
Two-sided post-only maker, both tokens at the touch, band **0.30-0.70**, tl 3-290, 50 sh per (bar, side), LAT 0.20 s,
SCAN 0.4 s, `evage < 1 s`, cancel-on-touch-move (re-quote when the target price changes), queue-ahead = displayed size at
the level consumed by prints (bug #11), tape-size cap (bug #28), fill from real taker sell prints in own-token space,
**terminal PnL = `win − q` + rebate 0.2·0.07·q(1−q)** (bug #37), bar-clustered SE, per-day, loss bars, worst LOO-coin,
3-term decomposition (half-spread@quote, drift quote→fill, adverse fill→settlement). Harness `lw5.py` = `lw4.py` + signals.

### 0.2 Signals (all causal at the snapshot; UP-space sign convention: s > 0 favours UP)
| id | definition |
|---|---|
| `imb1` | (ubs − uas)/(ubs + uas), top-1 |
| `imb3` | same on top-3 ladder sums |
| `flow5`, `flow20` | signed taker volume in UP space over the last 5 / 20 s, ÷ (total volume + 1) |
| `vol30`, `vol60` | std of 1-snapshot mid changes over the trailing 30 / 60 s (unsigned; WIDTH only) |
| `vsh30` | shares printed in the last 30 s (unsigned; WIDTH only) |
| `r1`, `r5`, `r20` | Binance `spot` return over the last 1 / 5 / 20 s, in bps, sign-mapped to UP |
| `est` | relay-lagged TWAP-so-far estimate `est_bps × cov` from `panel.parquet` (tl ≤ 90; 0 elsewhere) |
| `fair` | Gaussian binary pricer P(UP) = Φ((spot − strike)/(σ·√tl)), strike = TWAP[ws−62, ws−3] from `barrecon`, σ = trailing-60 s realised spot vol per √s; late window (tl ≤ 60) blended with `est` |
Every signed signal is clipped to [−1, 1] after dividing by its own 95th-percentile |value| (computed on the first 2 days only).

### 0.3 Modulators (each applied to the baseline, one at a time)
- **SKEW-B(s)**: favoured side at the touch, other side **1 tick behind**. **SKEW-O(s)**: other side **off**.
  **SKEW-Z(s)**: both at touch, size 50·(1 + s) / 50·(1 − s). Threshold |s| ≥ 0.2 else unmodulated.
- **WIDTH(x)**: both sides 1 tick behind when x ≥ its 70th percentile, at the touch otherwise (x ∈ vol30, vol60, vsh30, |imb1|, |flow20|, |r5|).
- **FAIR(k)**: quote a side only if `fair_side − touch_side ≥ k` ticks, k ∈ {1, 2, 3}; the side is otherwise off.
- **Latency sweep** on the best cell only: LAT 0.1 / 0.2 / 0.4.
### 0.4 Placebos (mandatory for any cell that beats baseline by > 1 SE)
(P1) sign-flipped signal; (P2) bar-shuffled signal (the same signal series taken from a random other bar of the same coin
at the same tl). A real modulator must beat both.
### 0.5 Maker-side hedge after a fill at q on token X (sized by |s|, else full)
(H0) hold to settlement; (H1) rest an ASK at X's touch from fill + LAT, cancel-on-move, up to 30 s, then hold the rest;
(H2) rest the ask at q + k (k = 1, 2 ticks). Note `X ask at P ≡ other-token bid at 1 − P` (merged book), so "rest a bid on
the other token at 1 − q − k" IS (H2). Scored on terminal PnL incl. exit proceeds, exit fill rate, exit price vs mid.
### 0.6 Family size and bar
Signed signals 8 × SKEW modes 3 + WIDTH 6 + FAIR 3 = **33 primary cells** (+ placebos + hedge 3 + latency 3 — not counted
as claims). Bonferroni over 33 at α = 0.05 ⇒ **|t| > 2.94** on the bar-clustered SE, AND both placebos must fail, AND ≥ 5 of
the days positive, AND worst LOO-coin ≥ 0. Anything short of that is reported as noise.
### 0.7 Part 2 — terminal re-score
Reproduce the rebate-farm headline cell (q .04-.60, tl 40-270, join, 50 sh, LAT 0.2, `mm.py`) and re-score its §5
conditioning cells on TERMINAL PnL: tl buckets, spread, hour-of-day, day-of-week, trailing volume (`volsh`), trailing vol
(`vol`), book imbalance (`ourdepth` vs `oppdepth`), placement (improve / touch / 1 / 2 behind), band. Then openmm §11's
`imb ≥ 0.2` cell with the queue, and the analytics doc's four leads from the maker side (UP vs DOWN token; 0.90-0.98
band; 04-08 UTC; tl 20-25) on the full-map harness. A verdict "changes" if its sign or its significance class
(|t| < 1 noise / 1-3 / > 3) changes between the drift-free and terminal metrics.
