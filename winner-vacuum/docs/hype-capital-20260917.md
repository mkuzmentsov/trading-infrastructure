> ✅ **Fee stack VERIFIED independently against `api.hyperliquid.xyz/info` `userFees` for our own
> sub-account (2026-09-17):** `userCrossRate 0.00045` = taker **4.50 bps**, `userAddRate 0.00015`
> = maker **+1.50 bps — a FEE, not a rebate**, `activeStakingDiscount 0.0`,
> `activeReferralDiscount 0.0`, `dailyUserVlm` 15 days of zeros (we have never traded here).
> Round trips: taker/taker **9.00 bps**, mixed 6.00, maker/maker **3.00** — against a **0.12 bps**
> spread. ⇒ **This agent's central claim is confirmed: no execution style clears the wall at our
> tier, and the maker lane is shut on fees alone before adverse selection is measured.**
> ⚠️ My own earlier framing to the other agents — "maker is the only arithmetically plausible
> lane" — was WRONG and has been retracted to them.

# CAPITAL.md — HYPE perp: allocation, sizing, ruin

**Owner:** portfolio-strategist. Siblings: `DATA.md`, `MODELS.md`, `VENUE.md`, `COST.md`.
**Status:** read-only analysis. No orders placed, no funds moved. Nothing here is a deploy proposal.
**Date:** 2026-09-17. **Bankroll assumed: $467** (Polymarket book; Hyperliquid master $0.0006 + sub $0.0009, verified live).

---

## THE CALL

**Move $0 today. Not because the minimum viable size is above our bankroll — it isn't — but because
there is nothing measured to size.**

This is a different answer from last round and the difference matters:

| | Polymarket (last round) | HYPE (this round) |
|---|---|---|
| Binding constraint | **capacity** — depth per coin (`hype $15`, `bnb $26`) | **cost vs unmeasured edge** |
| Was capital the problem? | partly | **no** — venue floor is ~$30, we have $467 |
| Adding capital would… | walk the book | **scale the loss, not the odds** |

On Polymarket the honest answer was "the size is below the floor". Here the floor is far below us.
HL's minimum order is **$10 notional** (szDecimals 2 ⇒ $0.83 granularity) and at 10× that needs
**$1.00 of margin**. Top-of-book depth is **$43.4k bid / $45.9k ask across ten levels** — three orders
of magnitude above anything a $467 book could want. *Capacity, the thing that killed half the
Polymarket ideas, does not bind here at all.*

What binds is arithmetic on the other side: **a taker round trip costs 9.0 bps against a 0.12 bps
spread — the fee is 75× the spread.** No amount of capital changes that ratio.

---

## TASK 1 — Should any capital move?

### The transfer is not free, and the framing matters

Moving money to HL is **taking size off an unproven-but-live book (t = 1.25) to fund an
unproven-and-unbuilt one (n = 0)**. Those are not symmetric. A t of 1.25 is a weak prior; it is still
a prior. HYPE has no strategy, no fill record, and 101 hours of tape (4 days, Sep 13–17).

### Reallocation vs new risk — argued separately, as required

- **Reallocation.** The Polymarket conclusion was to run at **k ≈ 0.5**. Executed, that halves stake
  ($1,748 → ~$874/day) and frees roughly **$233** of working capital. That money is surplus *whether
  or not HYPE exists*. Its alternative use is idle USDC.
- **New risk.** Anything beyond ~$233 comes straight out of live Polymarket stake and reduces a
  measured (if weak) positive mean to fund a zero.

**Only the ~$233 reallocation is even arguable. And it still loses.**

### What a HYPE book must clear

| Benchmark | Required net alpha |
|---|---|
| Beat idle USDC (4%/yr) on $233 | $0.026/day |
| Cover funding on a long (10.1%/yr, measured over 90d) | $0.065/day per $233 |
| **Cover 5 taker round trips/day** | **$1.12/day = 0.48%/day = 175%/yr** |
| Replace PM's contribution at k=0.5 (~$4.19/day) | 1.80%/day |

The third row is the one that decides it. **Costs are certain; the edge is not.**

### Zero-edge cost drag — bootstrap, 4,000 paths, actual HYPE daily returns, sign randomised

| Trades/day | Exposure | Certain annual cost | P&L p5 / p50 / p95 | P(profit) |
|---|---|---|---|---|
| 5 | $233 | **$408 (87% of bankroll)** | −824 / −403 / −11 | **5%** |
| 20 | $233 | $1,556 (333%) | −1,948 / −1,555 / −1,158 | **0%** |
| 50 | $233 | $3,853 (825%) | −4,250 / −3,849 / −3,441 | **0%** |
| 5 | $467 | $818 (175%) | −1,610 / −820 / −32 | **5%** |

A zero-edge HYPE taker at even *five* round trips a day burns **87% of the entire bankroll per year in
fees and funding alone**. At twenty, it burns the bankroll three times over. This is the single most
important number in the document.

### The maker lane is structurally shut, not just small

At our tier HL charges **maker +1.5 bps — a fee, not a rebate**. Both sides pay. Spread is 0.12 bps.
A pure market-making book pays **2.88 bps net per round trip** to capture 0.12. Unlike Polymarket —
where a 0.254 c/share rebate at least existed — **there is no subsidised lane here at all** until
volume tiers we cannot reach. Classic MM on HYPE is dead at *every* bankroll, ours included.

### Verdict on Task 1

**$0 moves.** The correct next step costs nothing: measure on the tape that already exists and the
history now backfilling. A paper/measurement phase requires no transfer, and a transfer before
measurement buys nothing except the cost drag above.

---

## TASK 2 — Sizing and ruin, conditional on something clearing Task 1

Run anyway, because the numbers change the answer to "what leverage" from intuition to arithmetic.

### Liquidation geometry (measured, not assumed)

HYPE `maxLeverage = 10`, margin table 52 ⇒ **maintenance margin 5%**. Liquidation at adverse move
`x = (1 − 0.05L) / (0.95L)`. Against **652 days** of actual HYPE candles (Dec 2024 – Sep 2026):

| Leverage | Liq at | P(liq) 1 day | 3 days | 7 days | 30 days |
|---|---|---|---|---|---|
| 1× | 100% | 0.0% | 0.0% | 0.0% | 0.0% |
| 2× | 47.4% | 0.0% | 0.0% | 0.0% | **2.1%** |
| 3× | 29.8% | 0.0% | 0.3% | 1.7% | **19.6%** |
| 5× | 15.8% | 1.1% | 9.1% | 22.2% | **49.7%** |
| 7× | 9.8% | 8.6% | 23.9% | 44.0% | 66.6% |
| **10×** | **5.3%** | **28.0%** | 53.5% | 67.9% | **82.6%** |

**At max leverage a HYPE position is liquidated on 28% of individual days.** The venue's own maximum
is not a setting anyone should ever use on this instrument.

### Drawdown and ruin — bootstrap, 20,000 paths, 90 days, drift removed

⚠️ **The 21-month sample is one regime.** HYPE went $10.26 → $87.94; raw drift is **+0.29%/day
(+187%/yr)**. Bootstrapping that drift in would manufacture a long-only "edge" that is just the bull
run. **Drift is set to zero below.** Long, paying measured funding, zero alpha:

| Lev | 90d maxDD p50 / p90 / p99 | 90d terminal p5 / p50 / p95 | **P(ruin, 90d)** |
|---|---|---|---|
| 1× | 45% / 66% / 78% | $170 / $398 / $937 | **0.0%** |
| 2× | 74% / 91% / 96% | $45 / $255 / $1,383 | **1.7%** |
| 3× | 90% / 98% / 100% | $9 / $130 / $1,749 | **19.6%** |
| 5× | 99% / 100% / 100% | $0 / $10 / $897 | **72.8%** |
| 10× | liquidated | ~$0 | **99.7%** |

**Median terminal wealth is below $467 at every single leverage**, including 1×. That is the funding
carry plus volatility drag on a 104%-annualised-vol asset, with no edge to offset it.

### Sizing rule, if an edge is ever established

- **Leverage ceiling 2×.** 3× carries a 19.6% 30-day liquidation probability — the same
  ~1-in-3 zero-edge ruin risk that was judged unacceptable on Polymarket. Same standard, same answer.
- **Prefer 1×.** The step from 1× to 2× raises median 90-day drawdown from 45% to 74% and ruin from
  0.0% to 1.7%, for a doubling of an unmeasured edge.
- **Short pays, long costs.** Funding is at the **+0.00125%/hr floor in 89% of hours**; mean
  +10.06%/yr, negative only 4.2% of hours. A long pays ~$0.39/day on $1,401 notional; a short
  *receives* it. Any long-biased book carries a certain 10%/yr headwind.
- **No Kelly.** Kelly is refuted on the Polymarket book, and the refutation transfers for the same
  reason: sizing on an estimated edge concentrates into the estimate's errors. With n = 0 fills here,
  there is no edge to size on at all.

### Noise floor — what is even detectable

| Net exposure | Day P&L sd | Days to detect +$4/day | +$8.37/day |
|---|---|---|---|
| $233 (half @1×) | $12.75 | 41 | 9 |
| $467 (full @1×) | $25.55 | 163 | 37 |
| $1,401 (@3×) | $76.64 | 1,468 | 335 |
| $4,670 (@10×) | $255.45 | 16,314 | 3,726 |
| *PM fleet, for comparison* | *$35.93* | *635* | *—* |

An honest and slightly counterintuitive result: **a 1× HYPE book is less volatile in $/day than the
current Polymarket fleet** ($12.75–$25.55 vs $35.93). Perps are not inherently the scarier book —
leverage is, and leverage is a choice. Note also that **leverage destroys detectability**: at 10× it
takes 16,314 days to distinguish a $4/day edge from noise. Leverage does not make an edge findable,
it makes it unfindable.

---

## TASK 3 — The staking lever

**Priced. It is unreachable, and by a wider margin than the Polymarket volume ladder was.**

Staking discounts multiply the fee rate. Tiers (venue agent owns confirmation):

| Tier | HYPE | Capital @ $83.25 | × bankroll | bps saved/taker | Break-even taker volume |
|---|---|---|---|---|---|
| **Wood** | 10 | **$832** | **1.8×** | 0.225 | **$5,575/day** |
| Bronze | 100 | $8,325 | 17.8× | 0.450 | $27,877/day |
| Silver | 1,000 | $83,250 | 178× | 0.675 | $185,845/day |
| Gold | 10,000 | $832,500 | 1,783× | 0.900 | $1.39M/day |
| Platinum | 100,000 | $8.33M | 17,827× | 1.350 | $9.29M/day |
| Diamond | 500,000 | $41.6M | 89,133× | 1.800 | $34.8M/day |

*(Break-even = net opportunity cost at 8%/yr less ~2.5% staking APR, divided by bps saved.)*

### The decisive line

> **The entire $467 bankroll converts to 5.61 HYPE. The first tier needs 10. We cannot reach Wood by
> staking every dollar we own — we are 44% short of the bottom rung.**

Even if we could: Wood buys **0.225 bps** off a 4.5 bps taker fee and needs **$5,575/day of taker
volume** to pay for its own capital. That is 11.9× our entire bankroll in notional, every day.

### And the capital being asked for is the worst capital on the menu

Staked HYPE is not a fee instrument, it is a **leveraged bet on the counterparty**, and it prices badly
on three axes at once:

1. **Price risk.** Unhedged long in a 104%-annualised-vol token with a **68% historical max drawdown**
   and **no Binance listing** — so no hedge leg, no cross-venue exit, undiversifiable.
2. **Liquidity risk.** HL unstaking runs a **~7-day queue**. You cannot exit during the event that
   makes you want to exit.
3. **Wrong-way risk.** This is the axis worth naming explicitly. Staked HYPE, trading collateral, and
   the venue are **the same credit**. A solvency or governance event at HL impairs the collateral,
   craters the token, and locks the unstaking queue *simultaneously*. Correlation in the tail is ≈ 1.
   The channel is not hypothetical — the March 2025 JELLY incident had HLP absorbing a large loss and
   the venue force-settling a market.

Priced as expectation this is small (≈2%/yr × ~70% joint loss ≈ $3/yr on $233). **Expectation is the
wrong statistic.** The relevant fact is that it removes the entire HL allocation in one stroke, cannot
be hedged, and cannot be exited while it happens. Staking converts a recoverable trading loss into an
unrecoverable one for **0.225 bps**.

**Verdict: do not stake at any size at this bankroll.** Unlike Polymarket's ladder — unreachable on
*volume* — this one is unreachable on *capital*, which is worse: volume can grow from trading, capital
cannot grow from not having it.

---

## THE HONEST QUESTION, ANSWERED

> *Is a HYPE book worth running at a $467 bankroll, or is the minimum viable size above what we have?*

**Neither, exactly — and the distinction is the finding.** The minimum viable size is **~$30** and we
have $467, so we are comfortably above the floor. Depth is $43k+ and irrelevant as a constraint. The
book is not too small.

**It is that there is no edge, and the cost of looking for one with live capital is 87% of the bankroll
per year at just five trades a day.** Capital is not the scarce resource here. A measured edge greater
than 9 bps per round trip is, and nobody has one yet.

The instrument is also not obviously wrong. A 9 bps round-trip hurdle against a 91 bps hourly sd means
a strategy needs to predict ~0.10σ of an hour — a real bar, but not an absurd one, and materially
easier than anything Polymarket's quadratic fee allowed. **HYPE deserves measurement. It does not yet
deserve capital.**

---

## WHAT WOULD REVERSE THIS CALL

Ordered by how much each would move me:

1. **A net edge > 9 bps per round trip, out of sample, on tape we did not fit on.** The single
   necessary condition. Below that, no sizing exists.
2. **A short-biased or funding-harvesting structure.** Funding is at the floor 89% of hours and
   positive 96% — a short *collects* ~10%/yr instead of paying it. That flips a headwind to a tailwind
   and is the one structural asymmetry on this instrument I would want tested first.
3. **A maker rebate becoming reachable** (volume tier where maker goes ≤ 0). Reopens a lane that is
   currently shut by arithmetic, not by skill.
4. **Polymarket deteriorating materially** — if the live book's t falls toward 0, the opportunity cost
   of the ~$233 surplus drops and the bar for an alternative home falls with it.
5. **A larger bankroll.** Would *not* reverse it on its own — costs scale with capital — but it would
   make the Wood tier arithmetic non-absurd somewhere north of ~$5k.

**What would NOT move me:** a profitable backtest on the 101-hour tape (4 days, single regime); any
long-only result bootstrapped with the +187%/yr drift left in; or a win-rate.

---

## IF SOMETHING IS EVER TRIALLED — revert path and judging metric

Stated so the option exists, **not** as a proposal. The user decides transfers and deploys.

- **Revert path:** HL sub-account → master → `hyperliquid_withdraw_usdc` → Polymarket. Reversible in
  one hop while nothing is staked. **Staking breaks the revert path** (~7-day queue) — which is a
  second, independent reason not to stake.
- **Judging metric — not PnL.** At $233 of exposure, 41 days are needed to detect $4/day; a month of
  PnL is noise. Judge on **realised cost per round trip vs the 9.0 bps model**, and on **fill rate at
  the quoted price**. Those are measurable in days, not quarters, and they are what the sizing above
  actually depends on.
- **Kill condition:** realised round-trip cost exceeding the model, or any liquidation at any size.

---

## SOURCES FOR EVERY NUMBER

- Account balances: `hyperliquid_get_accounts_overview`, live.
- Instrument (maxLev 10, szDecimals 2, margin table 52): `hyperliquid_get_meta`, live.
- Book depth / 0.12 bps spread: `hyperliquid_get_orderbook`, live.
- 652 daily + 5,001 hourly candles: HL `info/candleSnapshot`, Dec 2024 – Sep 2026.
- Funding: HL `info/fundingHistory`, 500 hourly points / 90 days.
- Tick tape on disk: `every-tick-single/data/pq-venue/hl/` — 101 hourly parquets, HYPE only,
  2026-09-13 14:00 → 2026-09-17 18:00, 74 MB. **`data/hl-hist/` does not exist yet.**
- Staking tiers: [Hyperliquid Docs — Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees);
  [Hyperliquid Fees 2026](https://hiperwire.io/explainers/hyperliquid-trading-fees-explained).
  **Venue agent to confirm in `VENUE.md`.**
