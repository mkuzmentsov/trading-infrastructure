# Vacuum replay vs live — 30 Jul 13:00 → 01 Aug 05:00 UTC (btc mrec)

`replay.py` re-derives the vacuum's decisions from the 100ms mrec snapshots and
joins them to the live bot's own event log for the same bars.

Data: 41 btc mrec hours, **488 bars with a resolution**, 479 overlapping the
live log.

## 1. Does the backtest match live? Yes — exactly.

| check | result |
|---|---|
| lock decision (UP / DOWN / skip) agrees with live | **479 / 479 = 100.00%** |
| bars where both locked | 290 |
| backtest says the lock was correct | **290 / 290** |
| live settles in the window | 25 |
| backtest win/loss verdict matches the live settle | **25 / 25** |

Getting to 100% required one correction to the first replay: the vacuum's
authoritative lock is taken **at/just after close** (`vacuum.py:481`,
`MIN_LEAD_BPS`), not from the pre-close lead that decided the resting order.
Using the pre-close lead produced 3 false locks on bars the live bot skipped
with `tie_print_lock_off` — all 3 were bars where the lead decayed through the
3bps gate in the last seconds. With the close lead, the disagreement is zero.

## 2. Where would we lose? Below 2bps — and the gate is already above it.

Lock accuracy by |lead at close|, over all 489 resolved bars (this ignores the
gate, so it shows what the gate is protecting us from):

| \|lead\| | bars | lock correct | wrong |
|---|---|---|---|
| 0.0–0.5 bps | 38 | 19 (**50.0%**) | 19 |
| 0.5–1 bps | 37 | 33 (89.2%) | 4 |
| 1–2 bps | 73 | 66 (90.4%) | 7 |
| 2–3 bps | 49 | 49 (100%) | 0 |
| 3–5 bps | 96 | 96 (100%) | 0 |
| 5–8 bps | 77 | 77 (100%) | 0 |
| 8–15 bps | 83 | 83 (100%) | 0 |
| ≥15 bps | 36 | 36 (100%) | 0 |
| **≥3 bps (the live gate)** | **292** | **292 (100.00%)** | **0** |

Breakeven is 99.0% (buy at 0.99 → +$0.01 on a win, −$0.99 on a loss). So:

- **Under 0.5 bps the signal is a coin flip** (50.0%). Every loss in the sample
  lives below 2 bps; that is the entire danger zone.
- The gate at 3 bps sits with ~1 bps of clearance above the last bucket that
  produced any wrong lock at all.
- Thinnest correct locks in the sample: −3.01, −3.02, −3.05, −3.06, +3.07 bps.
  Those are the bars that would flip first if the gate were loosened.

**Zero losing bars in this window** — consistent with live (30 Jul, 31 Jul and
01 Aug were all clean). The two real lifetime losses (28 Jul −$147.98,
29 Jul −$149.49) are **outside the mrec retention window**, so this replay
cannot reproduce them; nothing here validates or refutes the fitted
12:30–16:00 UTC session-size rule.

## 3. Fill model is still an upper bound (unchanged conclusion)

Counting every taker SELL print on the locked token at ≤ our bid within the
45s fire window: **190 bars show supply vs 25 live fills — 7.6× optimistic**,
because it ignores queue position (other bids sit at the same price).
Use it to answer "was there any supply at all", never to size expected PnL.

19 of the 25 live fills have matching qualifying prints in the tape; the other
6 have none within 180s, most likely dropped prints in the recorder's CLOB
trade subscription (the fills themselves are real — they reconcile to the cent
in the on-chain ledger).

## 4. Correction: the "+45.2s recurring counterparty" was an artifact

Every live fill is stamped **+45.1 to +45.4s after close**, which had been read
as one recurring counterparty dumping at a fixed lag. The tape says otherwise:
the qualifying sell prints are spread across **0.1s → 36s** after close
(p50 ≈ 20s). +45.2s is simply when `VAC_FILL` is emitted — the end of the
`fire_max=45s` window, i.e. our own polling cadence, not the counterparty's
timing. Supply is broad and early, not a single late actor.

One consequence worth testing: 11% of qualifying prints arrive **after** the
45s cutoff (out to ~108s), so `snipeFireMaxSecs` may be leaving fills on the
table — but redemption ties up the account, so a longer window trades fills
against order-placement failures on the next bar.
