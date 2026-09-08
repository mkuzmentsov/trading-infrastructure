# Wallet study — 0xfd9b763674cb096cacec059fcfe60ae82aae09e8 ("Sylldra")

Date: 2026-08-30. Question asked: *"how is this account so stable and earning so much"*.
Answer: it isn't, any more. Gross profit is real but ~40% of it is Polymarket's taker fee,
and the high-volume lane went fee-negative in July/August.

## Data
Full history from inception, `data-api /activity` paginated with `&end=<ts>` (offset caps at 5000):
**2026-04-09 → 2026-08-30, 7,957 activity rows, 5,317 TRADEs, 2,608 REDEEMs, 32 rebate rows.**
Resolution from gamma `&closed=true` (3,522 conditions, 100% resolved).
Scratch scripts: `/private/tmp/.../scratchpad/{early,res2}.py` (pattern is reusable — see whalepnl.py).

## What it does
- **Only** `{btc,eth,sol}-updown-5m`. Nothing else, ever.
- **BUY only — 5,317 buys, 0 sells.** Pure buy-and-hold-to-resolution.
- Fixed micro clips: **mean $8.52**, median ~$9, cap ~$15-30. ~37 clips/day, **1 clip per bar** in 2,694 of 3,486 bars.
- Enters **mid-bar**: median 140s into the 5m bar (tl≈160s). Entry prices cluster **0.45-0.60**.
- Roughly **50/50 taker vs maker** (2,745 clips appear in the taker-view `/trades` feed, 2,572 do not).
  Taker clips are the *cheap* side (median px 0.490); maker clips are the *rich* side (median 0.560).
- No side bias: Up/Down split flips month to month, and the base rate on its own bars is 49.6% Down.

## Headline numbers
| | gross | est. taker fee | **net** |
|---|---|---|---|
| lifetime (4.7 mo, $45,283 staked) | +$2,663 | −$1,085 | **+$1,568 (+3.46% ROI)** |

`lb-api /profit` reports **$2,713** — that is **gross of fees**. Volume $95,421 (lb counts both legs).
143 trading days, 58% up-days, **max drawdown −$536** (=34% of net profit). Daily-Sharpe *looks* like 4.7
annualised only because the clip size is $8.50; the smoothness is a **sizing artifact, not an edge property**.

## The edge, decomposed
Calibration is genuinely positive and near-uniform: it buys at price *p* and wins at ≈ *p*+0.03.
That +3pp is almost exactly the size of the crypto taker fee (3.5% of notional at p=0.50). Two lanes:

**Lane A — late-bar cheap entries. REAL, persistent, tiny.**
| tl | clips | stake | net ROI |
|---|---|---|---|
| ≤0s (post-close) | 168 | $1,270 | +17.2% |
| ≤15s | 284 | $1,879 | **+19.9%** |
| ≤45s | 355 | $2,517 | +15.5% |

px<0.30 lane net by month: Apr +$155, May +$75, Jun +$96, Jul +$132, **Aug +$174** — the only
lane alive in every month. Edge vs price: +5.7pp at 0.01, +12pp at 0.075, **+21.9pp at 0.154**.
Includes 51 clips at exactly $0.01 (35sh = $0.35 risk, $34.65 payoff) fired at tl −15…+45s.
This is our own [[settlement-snipe-edge]] / cheap-tail family, taken from the *buy* side.

**Lane B — mid-bar near-50c bets. Was the money, is now fee-negative.**
px 0.40-0.60, net ROI by month: Apr +2.74%, May +3.15%, Jun +1.75%, **Jul +0.01%, Aug −2.21%**.
tl 210-270s alone: −$451 net on $12,326. The gross edge decayed below the 3.5% fee.

Whole-book monthly net: Apr +$673, May +$477, Jun +$363, Jul +$109, **Aug −$54**.
And they **sized up ~6×** in the last 9 days (daily stake $10-200 → $600-1,300) straight into that
negative regime: 08-22…08-30 net ≈ −$272.

## Why it looked stable
1. $8.50 clips × 5,316 bets → law of large numbers smooths the equity curve.
2. Near-50c binaries have a **symmetric ±$4-15 payoff**, so no −$30 tail events like our 0.99 lane.
3. Polymarket's displayed profit is gross of the taker fee, which is invisible on the profile page.

## Transfer to us
- ⚠️ **Fee formula correction** (docs.polymarket.com/trading/fees.md, read 08-30):
  `fee = shares × feeRate × p × (1−p)`, **Crypto feeRate = 0.07**, makers 0, maker-rebate pool 20%.
  README §1 already had `0.07·p(1−p)` right; the **memory file `infra/pm-fees-tiers.md` was stale**
  (`0.04 × min(p,1−p)` — wrong shape and wrong rate) and is now corrected. At p=0.50 the real fee is
  **$1.75/100sh (3.5% of notional)**; at p=0.99 it is $0.07/100sh. Our vacmaker's 0.99 lane pays a
  **25× smaller** fee than this wallet's mid-price lane — that fee asymmetry is a big part of why
  our lane survives and theirs is dying.
- Nothing here to copy at the top of the book. The only lane worth a second look is the ≤45s /
  ≤0.30 slice, which is the same seam we already documented, and it caps out at ~$150/month
  because there is no size in it.
- Confirms [[reversion-priced-out]] indirectly: their mid-bar contrarian lane earned +3pp gross —
  real, but below the fee. "Priced out" now means "priced to within the fee".
