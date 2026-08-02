# Tails: where the money is, and why we can't take it — Sat 01 Aug 2026

## The view

`build_view.py` → `view.pkl`: **212,975 rows over 2,810 bars**, 6 coins,
Thu 30 Jul → Sat 01 Aug. One row per (coin, bar, side, second) for the last
180s of each bar, kept when that side is quoted in the tail zone (ask ≤ 0.10).

Every column is knowable **at that instant** — `ask ask_sz bid bid_sz spread
lead_bps trail gap_bps sigma_bps z p_model edge vol volsh` — and the single
future-looking column is the label `won`. That separation is deliberate: two
earlier passes at this question produced large fake edges purely because the
*entry rule* peeked at the future. Build features causally and the bias can't
enter.

`adverse.py` replays the tape forward from a decision instant and fills only
when a taker actually prints against our price.

## 1. The diffusion model is not usable — reversal is far rarer than Gaussian

Calibration of `p_model = Φ(−gap/(σ√t))` against realised outcomes:

| p_model | n | model says | actually won |
|---|---|---|---|
| 0.00–0.05 | 166,284 | 2.5% | **1.51%** |
| 0.05–0.10 | 20,415 | 7.5% | **3.71%** |
| 0.10–0.15 | 12,269 | 12.5% | **5.15%** |
| 0.20–0.25 | 3,570 | 22.5% | **6.58%** |
| 0.30–0.35 | 613 | 32.5% | **5.87%** |

The model over-predicts reversal everywhere, badly, and the error grows with
the prediction. Intra-bar price behaviour is **momentum, not diffusion** — once
a lead exists it tends to persist, so a driftless random walk massively
overstates the chance of a flip. Any strategy that buys tails because a
Gaussian model calls them cheap will buy every single one and lose.

## 2. The market's tail ask is rich — but the spread is exactly the richness

Realised win rate against the quoted ask:

| ask | n | implied | actual | edge |
|---|---|---|---|---|
| 0.01 | 59,884 | 1.0% | 0.15% | −0.85 pp |
| 0.03 | 18,789 | 3.0% | 0.95% | −2.05 pp |
| 0.05 | 14,532 | 5.0% | 3.08% | −1.92 pp |
| 0.08 | 13,201 | 8.0% | 6.04% | −1.96 pp |
| 0.10 | 11,737 | 10.0% | 6.68% | −3.32 pp |

Every bucket negative → **buying tails is −EV at every price**, which is the
favourite-longshot bias and confirms the earlier scan.

The tempting inversion — sell the tail, i.e. buy the favourite — dies on the
spread. The tail bid sits ~1c under the tail ask, so buying the favourite costs
`1 − tail_bid`, and against that price the favourite's win rate is a coin-toss
around break-even: net **−0.83% to +0.71%** ROI after the 0.07·min(p,1−p)
taker fee, averaging ≈0. **The mispricing and the spread are the same 1c.**

## 3. So the edge belongs to the maker — and adverse selection takes all of it

Resting a BUY on the favourite at `1 − tail_ask` (no taker fee) looks excellent
unconditionally: **+0.85 to +3.68 pp**, mean **+1.63c/share** over 212,975
observations.

It does not survive contact with fills. Replaying the tape and filling only on
a real taker SELL print at or below our price:

| decision | quoted | quoted win | filled | fill rate | filled win | **adverse selection** | realised EV/share |
|---|---|---|---|---|---|---|---|
| t−15s | 2,126 | 98.87% | 463 | 21.8% | 96.11% | **−2.76 pp** | **−0.0089** |
| t−60s | 1,456 | 97.39% | 526 | 36.1% | 93.35% | **−4.04 pp** | **−0.0206** |
| t−120s | 769 | 96.75% | 368 | 47.9% | 93.21% | **−3.54 pp** | **−0.0065** |

Adverse selection (−2.8 to −4.0 pp) is consistently **larger than the entire
unconditional edge (+1.3 to +2.2 pp)**, so realised EV is negative at every
decision time.

The mechanism is visible in the per-price detail at t−60s:

| resting px | fill rate | filled win% | EV/share |
|---|---|---|---|
| 0.99 | 30.2% | 100.00% | +0.0100 |
| 0.95 | 47.0% | 90.32% | −0.0468 |
| 0.92 | 50.6% | 85.71% | −0.0629 |
| 0.90 | 56.1% | 81.08% | **−0.0892** |

**Fill rate rises and win rate falls together, monotonically.** You are filled
most often exactly where you are most often wrong, because the thing that
brings a seller down to your bid is the favourite going bad. Getting filled is
the signal that you were wrong.

Note the one exception, and it is the business we are already in: at **0.99**
the fill is +0.0100/share with a 100% win rate. That is the vacuum — and it
works precisely because it quotes *after* the close, when the outcome is no
longer uncertain and the seller's motive is capital release rather than
information.

## Verdict

There is no tail trade here. Buying tails is −EV (the market is rich by
exactly the spread); crossing for the favourite is ≈0 after fees; resting for
the favourite is +EV on paper and −EV in reality once fills are conditioned on.
The only profitable resting bid in this dataset is one placed after the
uncertainty is gone.

Anything that reopens this should start by explaining what makes *our* fill
non-adverse. Speed does not: the taker who hits us is the informed party.

---

# Can adverse selection be reduced? Yes — by quoting only when the bar is already decided

Same fill-replay method, split by **|lead| in bps at the moment we quote**:

**t−60s decision**

| \|lead\| | quoted | q_win | filled | f_win | fill rate | adverse | EV/share |
|---|---|---|---|---|---|---|---|
| 0–5 bps | 181 | 92.27% | 93 | 84.95% | 51.4% | **−7.32 pp** | −0.0770 |
| 5–10 | 647 | 96.75% | 267 | 93.26% | 41.3% | −3.50 | −0.0154 |
| 10–15 | 345 | 99.13% | 108 | 97.22% | 31.3% | −1.91 | −0.0019 |
| **15–20** | 143 | 100% | 30 | **100%** | 21.0% | **0.00** | **+0.0117** |
| **≥20** | 61 | 100% | 16 | **100%** | 26.2% | **0.00** | **+0.0144** |

Adverse selection falls monotonically with the lead and **reaches exactly zero**
once the lead is decisive. The fill rate falls with it — you are quoted at less
often, but the fills you get are no longer informed.

The threshold scales with time remaining, as it must:

| decision | lead needed for ~zero adverse | EV/share there |
|---|---|---|
| t−15s | ≥ 5 bps | +0.0040 … +0.0121 |
| t−60s | ≥ 15 bps | +0.0117 … +0.0144 |
| t−120s | ≥ 20 bps | +0.0377 |

**Mechanism.** Adverse selection is the price of *uncertainty about the
outcome*, not a latency problem. While the bar is live and close, the person
crossing into your bid knows something you don't. Once the lead is large
relative to the move still available, there is nothing left to know — the
seller is releasing capital, exactly like the post-close vacuum counterparty.
This is the same edge the vacuum already harvests at 0.99, extended backwards
in time: **you cannot out-run the informed trader, so quote only where no
informed trader exists.**

⚠ Normalising by volatility does NOT work. Bucketing by
`z = |lead| / (σ√t)` leaves adverse selection flat at −4 to −5 pp across every
z bucket, improving only at z ≥ 3 (−1.71 pp). The causal realised-vol estimate
is a poor scaler here — the same miscalibration that made the Gaussian model
useless. Use a raw bps gate per decision time, not σ√t.

⚠ Sample sizes at the useful thresholds are small (16–30 fills per cell). This
is a hypothesis with a clean mechanism and a monotone gradient behind it, not
a proven edge. It needs more mrec days before anything is deployed.

---

# Full-bar ≤5c tail buy (hold-to-redemption / 50c TP) — Sun 02 Aug 2026

User spec: "buy losing side for ≤5c, hold till redemption (or sell at 50c)".
The last-180s view above already covered most of this; the open question was
entries EARLIER in the bar. `fullbar_tail.py` answers it: streaming causal
replay over the FULL live bar, one bet per (bar, side) at the first trailing
ask ≤ 0.05, taker fee 0.07·p(1−p) both ways.

Data: Thu 30 Jul 13:00 → Sun 02 Aug 06:00 UTC, 6 coins, 4,403 bars, 4,499 bets.

**POOLED: win 3.09% | EV/share hold −0.0176 (t = −6.8) | tp50 −0.0196.**
ROI −36% hold, −41% with the 50c take-profit. Negative in every price bucket
(1c: 0/134 wins; the +0.75c blip at 2c is 5 wins/173, p=0.27 vs fair — noise),
every time-left bucket, every coin.

- **Early entries (tl>180s, outside the old view): n=172, EV −0.0169** — same
  favourite-longshot tax earlier in the bar. No unmeasured zone remains.
- **The 50c TP is worse than holding, again**: 95% of the 139 winners pass
  through 50c (payoff capped ~0.95 → 0.48 net of fees) to rescue only 84
  spike-then-die losers. Confirms the 326-bet tick-path result structurally.
- Deployed at the $5/bet capacity wall (~1,660 qualifying bets/day fleet-wide)
  this bot would lose ≈ $2,900/day.

**Verdict: do not build.** Identical mechanism to the −38%…−72% scan and the
live tail fleet that was halted 2026-07-17; the extra 1.3 days and the
full-bar entry window change nothing. The tail ask is rich by more than the
flip rate at every price and every time.
