# Two-sided maker pair ("lock both coins") — Sat 01 Aug 2026

`pairarb.py`, 2,904 bars, 6 coins, mrec Thu 30 Jul → Sat 01 Aug.

## The premise is sound; the rebate part of it is not

UP + DOWN always pays exactly $1.00, so resting a bid on both legs costs
`ub + db` and redeems 1.00. That sum is **< 1.00 on 91.8% of snapshots**,
dominant mode **0.99** (1.35M snapshots) → **+1c per filled pair**. The taker
version is the mirror image and never works: `ua + da >= 1.01` on 99.94% of
snapshots, so crossing for both sides pays ~1c *over* par before fees.

⚠ **There are no rebates to farm in these markets.** Measured Sat 01 Aug:
0 of 11,329 reward-configured markets are `updown-5m`, 14-day earnings $0.00,
and zero negative `fee_rate_bps` across 3,484 lifetime trades. A rebate-driven
pair farm cannot work here at any size. The good news is it does not need to —
the 1c spread is worth more than any rebate would have been.

## What actually happens: single fills eat everything

Rest both bids at t−150s, join the bid, replay the tape:

| outcome | share | PnL each |
|---|---|---|
| BOTH legs filled | 58.7% | **+0.0213** /pair |
| ONE leg filled | 34.1% | **−0.2757** /single (hold) |
| NEITHER | 7.3% | — |

Net **−0.0814/bar**. The single-fill loss is 13× the pair profit.

Exit choice barely matters — hold −0.2757, unwind at the bid −0.2849, cross for
the missing leg −0.2849 per single. By the time you know you are single-filled,
the damage is already priced.

Quoting deeper raises the per-pair take but raises the single rate with it:

| decision | offset | both% | +/pair | one% | −/single |
|---|---|---|---|---|---|
| t−150s | join | 58.7% | +0.0213 | 34.1% | −0.2757 |
| t−150s | −3c | 47.9% | +0.0813 | 45.4% | −0.2656 |
| t−150s | −8c | 37.9% | +0.1819 | 54.5% | −0.2478 |
| t−60s | join | 35.3% | +0.0255 | 40.6% | −0.1950 |
| t−60s | −8c | 25.2% | +0.1893 | 59.6% | −0.2232 |

Every configuration is net negative, by roughly 2:1.

## The low-volatility hypothesis is refuted — balanced is the WORST case

Split by |lead| at the decision instant:

| \|lead\| | bars | both% | +/pair | one% | −/single | **net/bar** |
|---|---|---|---|---|---|---|
| 0–4 bps | 1,431 | 63.2% | +0.0244 | 35.5% | −0.3775 | **−0.1186** |
| 4–8 | 821 | 61.1% | +0.0189 | 33.1% | −0.2248 | −0.0629 |
| 8–12 | 375 | 53.3% | +0.0165 | 31.5% | −0.1168 | −0.0279 |
| 12–16 | 167 | 40.7% | +0.0163 | 32.3% | −0.0491 | **−0.0092** |
| 20–24 | 61 | 23.0% | +0.0157 | 31.1% | −0.0847 | −0.0228 |

A calm, balanced market is the **worst** place to run this, 13× worse than a
decided one — the opposite of the intuition that low volatility helps.

The reason is the price of the leg you are left holding. In a balanced market
both bids sit near 0.50, so a single fill leaves a 50c position that loses 50c
when it is wrong. Once the market has picked a side, the loser's bid is only a
few cents, so being single-filled on it costs a few cents. Balance does not
protect you — it just makes the wrong leg expensive.

## Verdict

Negative in every variant tested, but the gradient points somewhere specific:
the loss shrinks 13× as the outcome becomes decided, and the limit of that
trend is a single resting bid on a token that is already ~certain — quoting
0.99 on the winner, with the "other leg" worth a cent. That is the vacuum.

This is the third independent study today (tails, adverse selection, pair arb)
whose optimum lands on the same rule: **quote only where the outcome is no
longer in question.** Everywhere else, whoever trades with you knows more.

Untested variants that remain, in order of how much I would trust them:
1. Pair on markets that ARE in the rewards programme (11,329 of them) — there
   the rebate is real income and the spread economics differ. Needs a fresh
   recorder; none of our mrec data covers those markets.
2. Asymmetric pair: rest the cheap leg only when the expensive leg is already
   filled (sequential), sized so the single-leg loss is bounded by a few cents.

---

# CORRECTION (Sat 01 Aug, later) — rebates DO exist, and two of my numbers were wrong

## 1. Crypto markets pay a maker rebate. My earlier "structurally impossible" was wrong.

Straight from a live `btc-updown-5m` market on gamma:

```
feeType                  crypto_fees_v2
feeSchedule              {exponent: 1, rate: 0.07, takerOnly: true, rebateRate: 0.2}
makerRebatesFeeShareBps  10000
rewardsMinSize           50        rewardsMaxSpread  4.5
```

Takers pay `0.07 · p(1−p)`; **makers receive 20% of it**:

| p | taker fee/sh | **maker rebate/sh** |
|---|---|---|
| 0.50 | 0.01750 | **0.350 c** |
| 0.75 | 0.01313 | 0.263 c |
| 0.90 | 0.00630 | 0.126 c |
| 0.99 | 0.00069 | **0.014 c** |

What I tested earlier was the *liquidity rewards* programme
(`get_current_rewards`, `get_earnings_for_user_for_day`) — a different
mechanism — and wrongly generalised its $0 to "no rebates in these markets".

Our measured $0 was nonetheless right *for the vacuum*: it quotes at 0.99,
where the rebate is 0.014c/share (~$1.61 across all-time maker volume) and the
order sits ~49c from mid, far outside `rewardsMaxSpread 4.5`. The rebate is
maximal at 50/50 — exactly where a pair farm operates.

## 2. The single-leg unwind was mismeasured — it costs 8c, not 28c

The first pass priced the unwind at the **last book before close**, i.e. it
held the orphan leg to the end of the bar. That is not "sell it", which is the
actual variant. Pricing the unwind at the book *at the moment of the fill*:

| reaction | single-fill cost | net/bar incl rebate |
|---|---|---|
| 1.0 s | −0.0844 | **−0.0125** |
| 0.3 s | −0.0821 | −0.0118 |
| 0.1 s | −0.0805 | −0.0112 |

Corrected economics at t−150s, join-the-bid, 2,904 bars:

- BOTH fill 58.7% → **+0.0213**/pair
- ONE fills 34.1% → **−0.0844**/single (was −0.2757)
- maker rebate → **+0.00375**/bar
- **NET −0.0125/bar** (was −0.0814)

So the honest verdict moves from *hopeless* to *close but still losing*. The
rebate covers about a quarter of the remaining gap.

**Speed is not the missing piece.** Cutting reaction from 1.0s to 0.1s recovers
0.4c of the 8.4c single-fill cost — the cost is the spread plus the immediate
adverse move, not latency. Anything that closes the last ~1.1c/bar has to
attack the 34% single-fill rate itself, not how fast we react to it.
