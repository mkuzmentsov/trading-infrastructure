# "Start trading HYPE" — the answer
**2026-09-17. Four agents, read-only throughout. No orders, no transfers, nothing deployed.**

## The answer

**There is nothing to trade on HYPE at our size. The one structure that works is a funding carry
that needs 2.4× our bankroll and is not a HYPE strategy — it is a carry position in a module we
already run.**

## ⚠️ First, an error of mine that I propagated to all four agents

I told every agent **"HYPE has no Binance listing, HL is the only book, no cross-venue reference."**
**Wrong.** No *Binance* listing — but **Bybit listed HYPEUSDT perp the same day**, as did OKX, Gate
and Bitget. Bybit serves 1m klines, funding and hourly OI from **2024-12-05**: 937,864 rows, 100.0%
complete, zero missing bars.

Validated as a proxy over 5,074 overlapping 1m bars: **return correlation 0.9820**, vol ratio 0.990.
⚠️ And the trap arrived on cue — a persistent **+0.91 bps level offset** between venues. Small,
stable, and exactly what killed a real signal on Chainlink/Binance. **Never compare levels.**

⇒ **A cross-venue lead-lag study is structurally possible and has not been done.** (The venue
agent's "the only independent price for HYPE anywhere is HL spot" is also too strong — what is true
is narrower: **HL's *oracle* excludes external CEXes**, so funding/margin/liquidation run off HL's
own book. That stands.)

## Intraday is closed — twice, from two directions

**1. The perfect-oracle ceiling.** What an oracle that knows the sign and abstains when the move
cannot cover the fee actually earns, fee deducted:

| horizon | taker/taker | mixed | maker/maker |
|---|---|---|---|
| 1 s | **0.003 bps** | 0.009 | 0.040 |
| 5 s | **0.060** | 0.145 | 0.423 |
| 60 s | 2.299 | 3.404 | 5.079 |

**Below a minute there is nothing to compete for. Foreclosed, not underpowered.**

**2. Market making is negative before any fee.** Front-of-queue, 2 s quote life, **182,353 fills at
the touch**: capture **+0.020 bps** vs 1 s adverse selection **−0.376** ⇒ **−0.356 bps/fill at ZERO
fees, t = −92, 0 of 72 cells positive.**

**Directional control: a clean negative with a provably sound harness.** OOS AUC **0.5306** at 60 s;
shuffle placebo **0.4990** — *exactly* chance, so the pipeline does not leak; latency tell decays
monotonically 0.5306 → 0.5242 → 0.5176. The signal is real and worth **+0.94 bps gross against a
9.00 bps round trip.** All 36 configs negative. A tradeable +9 bps edge would have shown at t ≈ 7.8,
so this is a meaningful negative, not a shrug.

## ⭐⭐ The carry — real, replicated, and correctly priced at last

Funding on **15,634 hourly points from listing**: positive **93.4% of hours**, at the structural
floor in 66.0%, **all 22 months positive, all 22 leave-one-month-out positive**, and stripping the
**top 30 days entirely** still leaves +15.3%/yr.

⚠️ **Judge this on the floor share and the month-by-month consistency, NOT on a t-statistic.**
Monthly blocks are themselves persistent, so the carry's **t = +3.21 is optimistic** as a strict
significance claim (bug #53). What is load-bearing is **mechanical**: 66% of hours sit at exactly
the +0.00125%/hr floor and 22 of 22 months are positive — a venue feature, not an estimated
coefficient.

⚠️ **But funding alone flatters it.** Daily basis-change sd is **11.4 bps ≈ 4× the daily carry.**
Priced with basis mark-to-market — and with the **measured** spot fee rather than the assumed one
(the data agent assumed spot = perp 4.50 bps; the venue agent measured **6.72** from our own
receipts, so the round trip is **22.08 bps, not 18.00**):

| window | 30-d net | %/yr | break-even hold |
|---|---|---|---|
| full sample (21 mo) | +132.4 bps | +16.1% | 4.3 d |
| **last 12 months** | **+59.3 bps** | **+7.2%** | **8.1 d** |
| **last 6 months** | +55.8 bps | +6.8% | 8.5 d |

**Plan on ~7%/yr, not 16%** — the full sample is inflated by the launch era, and the t-stat *rises*
as the window shortens (+3.21 → +7.82 → +9.66) precisely because that era's variance drops out.
**0 of 21 months negative** (worst +21.7 bps), basis drag ≈ 0 (stationary). **This is a hold, not a
scalp.**

### Why we still cannot do it
- **Margin does not offset** (verified: `meta.collateralToken = 0`; `clearinghouseState` and
  `spotClearinghouseState` are separate balance classes; a live account with $8.2M spot shows perp
  accountValue $0.00). Both legs fund in full ⇒ **$1,112.67 against our $467.**
- ⚠️ **Tail risk**: the perp short liquidates on a **~+28% move at 3×** while a **staked** spot leg
  **cannot be sold for 7 days** ⇒ short gone, spot locked, **naked long HYPE with no hedge and no
  exit.** Either leave the spot unstaked or hold spare USDC to defend through the queue.

## Data: what we now have, and what does not exist

⚠️ **There is no 22-month 1-minute HL history.** `candleSnapshot` retains a **rolling ~5,000 candles
per interval**: 1m = **3.5 days**, 5m = 18 d, 1h = 215 d; only **4h and coarser** reach listing.
⭐ **Our own 100-hour recorder tape is finer than anything HL will ever sell back** — the recorder is
the only source of sub-hourly HYPE history on its home venue, going forward.

⚠️ And the API returns **spurious empties, non-monotonic in request width** (2h from 2025-06-01:
16d→192 rows, **32d→0**, 64d→83, 128d→851, 256d→2387). **Paging without retry-on-empty silently
under-reads and manufactures a fake wall.**

Built: `every-tick-single/data/hl-hist/` — **3.57 M rows, 713 MB**. A 1 s tick panel (360,601 × 114,
5 days, with 500 ms / 2000 ms lagged copies for the latency tell), a 21-month history panel (native
HL 4h/1d, returns published raw *and* de-drifted with the de-drifted flagged in-sample), the Bybit
1m proxy, `@107` spot, and complete hourly funding for six coins.

⚠️ Two tape facts: `t` is recorder receive time in **seconds**, `time` is exchange **ms** — conflating
them reports a 100-hour tape as 0.1 hours. Recorder latency p50 **368 ms**. Trade side was
**validated, not assumed** (`B` = aggressive buy, 76.6% at-or-above ask); a silent flip would have
inverted every flow feature.

## What I would do

1. **Nothing on HYPE.** Intraday is foreclosed; the carry needs 2.4× the bankroll.
2. **Fix the sub/master referral gap** — `activeReferralDiscount` is 0.04 on the master, 0.00 on the
   sub, and the MCP trades the sub. 4% of every fee, both sides, free.
3. **Keep the recorder running.** It is now the only source of sub-hourly HYPE history that will
   ever exist, and its value compounds while HL's own API forgets.
4. **The one unexplored lane**: cross-venue lead-lag HL↔Bybit, now that we know the listing exists.
   Minute bars cannot resolve it; our tick tape plus a Bybit tick recorder could.

⛔ **Closed in the same pass: open interest does NOT predict funding.** The carry's main forward risk
is further funding compression, so a crowding proxy that forecast it would have been worth real
money. The naive test read **day-clustered t = +7.3 to +7.8 in every cell**; under non-overlapping
blocks and an autocorrelation-preserving null it is **p = 0.276**. See bug #53 — and note it
**corrects this program's standing "null reads t ≈ 2-3" rule**, which does not hold on overlapping
windows.

✅ The data agent's open caveat — *"I assumed the HL spot taker fee equals the perp 4.50 bps, please
confirm"* — **is settled**: the venue agent measured **6.72 bps** from our own receipts, and the
carry table above is already repriced at the measured 22.08 bps round trip.
