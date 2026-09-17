> ⛔⛔ **ONE SECTION OF THIS DOCUMENT IS WRONG — the spot-leg identification. Verified 2026-09-17.**
> The claim that HL's spot universe holds *"multiple imposter tokens literally named HYPE"* and
> that the real pair hides under another name is a **data-join artefact**, not a venue fact.
> `spotMetaAndAssetCtxs` returns `[meta, ctxs]` where **ctxs has 845 entries against universe's
> 328** and each ctx carries its own **`coin`** field; zipping positionally misaligns every row
> (`universe[107]` is `@109` while `ctxs[107]` is `coin:"@107"`). The tell was three different
> 'tokens' reporting an identical circulating supply.
>
> **Joined correctly on `ctx['coin']`: there is exactly ONE token named HYPE (index 150), and its
> canonical pair `@107` (HYPE/USDC) is the genuine market — mid 83.3865 against a perp at 83.37,
> $115,517,727/day, circulating 298.8M, implied cap $24.9B.** `@207`/`@255`/`@232` are the same
> token against thinner stablecoins. **No imposters exist.**
>
> ⚠️⚠️ **`@109` — the leg this document puts at ~85% confidence — is `WOW`, mid $0.0003485, $0
> daily volume.** Trading it instead of HYPE would have been a total loss on the spot leg.
> The instinct (*'tape-gate the instrument, not the label'*) was right; the identification was
> inverted by the bug. **The spot leg is `@107`.**
>
> Everything else below — the zero-fee MM refutation, the required-edge table, the funding series,
> the mark-vs-oracle level gap — is independent of this and stands.

# COST.md — HYPE perp: the cost wall and the microstructure hunt

Owner: quant (cost wall + microstructure). Companions: DATA.md, MODELS.md, VENUE.md, CAPITAL.md.
Pre-registration: `scratchpad/PREREG.md`, written before any result was computed. Read-only study; no orders placed.

---

## VERDICT

**Every intraday family on HYPE is closed by arithmetic at our fee tier. The only structure that
clears the wall is the delta-neutral funding carry (long spot / short perp, both on HL), and it
clears it comfortably.**

Three findings, in decreasing order of confidence:

1. **Market making HYPE is dead, and not because of fees.** Front-of-queue (best case any maker can
   achieve), 2-second quote life: you capture **+0.020 bps** of half-spread and eat **−0.376 bps**
   of adverse selection at a 1-second markout. Gross **−0.356 bps per fill before any fee at all**.
   **0 of 72** (depth x UTC-hour) cells are positive at zero fees. t = −92. Add the 1.5 bps maker
   fee and it is −1.86 bps/fill, −3.7 bps/round-trip. *No rebate rescues this* — even HL's deepest
   maker tier (−0.3 bps, needs >3% of venue maker volume) leaves it at −0.06 bps/fill.
2. **Directional trading needs an IC we have never produced.** Required gross edge is 2.72 bps
   (maker/maker) to 9.28 bps (taker/taker) per round trip, invariant to horizon. Against realised
   vol that is an impossible per-trade forecast below 1 minute and a 0.13–0.46 IC at 5 minutes.
   Only the 1-hour maker/maker corner (IC 0.046) is not absurd — and it inherits finding 1.
3. **Funding is real, persistent and large enough.** 10 windows across 11 months: **+9.5%/yr mean,
   range +4.5% to +15.3%, positive in every window.** 68–87% of hours sit exactly on HL's
   hard-coded interest floor. A 9.28 bps taker round trip is repaid by **~3.6 days** of funding.

---

## 1. The cost wall, measured

| quantity | value | source |
|---|---|---|
| tick | 0.001 (= **0.128 bps** at $78) | 1.91M bbo rows |
| spread, **time-weighted mean** | **0.276 bps** | bbo, 100.2 h |
| spread = 1 tick, time-weighted | **81.4%** of the clock | bbo |
| taker fee | 4.50 bps | `userFees` (venue agent) |
| maker fee | **+1.50 bps — a fee, not a rebate** | `userFees` |
| staking / referral discount | 0.0 / 0.0 | `userFees` |

> ⚠️ **Correction to the brief.** The 0.12 bps figure is the *modal* spread. Time-weighted mean is
> **0.276 bps**, so maker/maker fees are ~11x the quoted spread, not 25x. But the number that
> actually matters is neither: the spread you *realise* on a fill is **+0.020 bps**, because you get
> filled disproportionately when the book is tight and the price is leaving. **Fees are 150x the
> spread you actually capture.**

**Slippage is not a constraint at our size.** Cost to sweep, median over 67k snapshots:
$1k → 0.06 bps, $5k → 0.15 bps, $25k → 0.63 bps. Ten levels hold $25k 75% of the time. Below
~$5k, slippage is an order of magnitude smaller than the fee and can be ignored in all sizing.

---

## 2. Task 1 — adverse selection, measured directly

Method: quote every 2 s at (best bid − d ticks) / (best ask + d ticks), **front of queue (Q=0)** —
deliberately the most generous assumption available, so a negative result is a bound. Fill = first
aggressor trade through our price. Benchmark = **pre-trade mid at fill − 1 ms**, validated: median
capture at d=0 is +0.063 bps = exactly half a tick, as it must be. Buy and sell pooled.

**Front-of-queue, 2 s life, buy+sell pooled, n = 182,353 fills at the touch:**

| depth | capture | adverse drift 1s | **gross (zero fee)** | net @ maker 1.5 | net @ best rebate −0.3 |
|---|---|---|---|---|---|
| touch | +0.020 | −0.376 | **−0.356** (t=−92) | −1.856 | −0.056 |
| 1 tick back | −0.171 | −1.096 | **−1.267** (t=−160) | −2.767 | −0.967 |
| 2 ticks back | −0.104 | −1.165 | **−1.270** (t=−151) | −2.770 | −0.970 |

At a 30 s markout the touch gross worsens to −0.498. **Deeper is monotonically worse** — the further
back you quote, the more selected the fill (measured out to 10 ticks: drift −1.64 bps).

**Robustness (all pre-registered):**
- **Per-day gross at the touch:** −0.310 / −0.376 / −0.339 / −0.384 / −0.335. **Leave-one-out range
  −0.347 to −0.362.** No day drives it.
- **By UTC hour:** all 24 negative. Best hour −0.198, worst −0.554.
- **Zero-fee break-even sweep: 0 of 72 (depth x hour) cells positive.** Max cell −0.198.
- **Wide-spread steelman:** the only bucket with positive zero-fee gross is spread ≥ 40 ticks
  (gross +1.21, n=242) — **0.14% of the clock**, and still −0.29 after the maker fee. Joining and
  pennying-in both fail. No lane there.
- **Order-lifetime sweep** 2 s / 10 s / 60 s and **queue-position sweep** (front-of-queue vs. full
  queue-ahead-from-l2Book): sign never flips. The realistic-queue version is *worse* (−1.86 gross).

**Why this differs from Polymarket.** There, the wall was adverse selection and the fee was zero for
makers. Here it is **both**, and the fee is the larger term (1.5 of the 1.86 bps, 81%). That makes
the conclusion *more* robust than Polymarket's, not less: the dominant term is a published constant,
not a fill-model estimate. **No fill model can rescue this**, which is the one thing that repeatedly
went wrong on Polymarket (bug #40: replay read −$82 where the fleet made +$203).

### Known bias, and its direction
I cannot see cancellations, so queue-ahead decays only by trades. In the full-queue run this made
fills late: at the median fill the real best bid was **2 ticks below our price**, i.e. the queue ahead
had been *cancelled*, not traded. Both fill-timing assumptions are therefore adverse, and I report
the **front-of-queue** number as the bound. If the tape double-counts volume (see §6), fill rates are
~2x optimistic — which also flatters the maker, so the kill holds a fortiori.

---

## 3. Task 2 — the required-edge table

Required gross edge is a **per-round-trip constant**; it does not shrink with horizon, while the
available move does. σ from 100 h of 100 ms mid. `required IC` = edge a sign-taking signal must have
with the h-horizon return, = req / (0.798·σ).

| horizon | σ (bps) | mean abs move | TT req 9.28 bps | MT req 6.00 | MM req 2.72 | verdict |
|---|---|---|---|---|---|---|
| **1 s** | 1.19 | 0.54 | IC 9.79 | IC 6.34 | IC 2.88 | **impossible — cost exceeds the entire move** |
| **10 s** | 4.40 | 2.78 | IC 2.64 | IC 1.71 | IC 0.78 | **impossible / dead** |
| **1 m** | 11.38 | 7.76 | IC 1.02 | IC 0.66 | IC 0.30 | **impossible / dead** |
| **5 m** | 25.27 | 17.66 | IC 0.46 | IC 0.30 | IC 0.135 | **dead / very hard** |
| **1 h** | 74.93 | 56.37 | IC 0.155 | IC 0.100 | **IC 0.046** | very hard / **only open corner** |

TT = taker/taker (2x4.5 + spread crossed). MT = maker/taker (1.5+4.5). MM = maker/maker
(2x1.5 − spread captured) — and note §2 shows the MM row is optimistic, since realised capture is
0.02 bps, not 0.276.

**The intuition pump.** If such a signal were traded every period, the **gross annualised Sharpe
required merely to break even** is 4.3 (1 h MM), 14.5 (1 h TT), 43.8 (5 m MM), 149 (5 m TT). House
record is **OOS Sharpe 0.79, and it was gate-rejected on DSR** (`algo-trading-bot`). Note the per-trade
IC bar is **invariant to selectivity** — trading only the best 1% of hours cuts your costs and your
sqrt(N) together, so it does not lower the bar on the trades you do take.

Cross-check with the portfolio agent: they read "9 bps ≈ 0.10σ of an hour" from σ=91 bps. Same
arithmetic, different statistic — 0.10 is required *return/σ*; the required *correlation* for a
sign-taking signal is 0.155. My σ is 74.9 bps (4 days of mid) vs their 91 bps (candles, longer
window); the gap is regime, and it moves the 1 h IC between 0.128 and 0.155. Conclusion unchanged.

**Bound:** *every horizon at or below 1 minute is closed by arithmetic on HYPE at our tier,
independent of signal quality.* That is not a refutation of any particular model — it is a
statement that the model does not exist that could clear it.

---

## 4. Task 3 — the microstructure hunt

The table leaves only the 1-hour corner open, and §2 closes the maker leg of it. **I did not run the
OFI / trade-sign / queue-dynamics battery**, and that is a decision, not an omission: those are all
sub-minute signals, and §3 shows a sub-minute signal cannot clear the wall *at any strength*. Running
40 cells there would be spending tests on a family already bounded to zero. Pre-registration says
count your tests; the cheapest test is the one you don't need.

What I did test in that family, because it is *not* sub-minute:

**Mark vs oracle.** Mark sits **−1.84 bps below oracle persistently** (mean over 353k ctx rows;
independently −1.76 bps over a separate 500 h window in March). σ of the divergence is 8.8 bps.
⚠️ **This is a level gap, exactly the trap from the Binance/Chainlink episode** — any mark-vs-oracle
signal must be differenced against its own −1.84 bps mean, not against zero, or you will "discover"
a permanent short signal that is really a constant. The gap is not an inefficiency: it is the market
pricing the funding a short will collect.

---

## 5. What survives: the funding carry

This is the one place the arithmetic works, and it works because the payoff is a **recurring cash
flow, not a forecast**.

| window | annualised | hrs funding < 0 | hrs pinned at floor | mean premium |
|---|---|---|---|---|
| 2025-11 | +13.84% | 3.8% | 71.8% | +2.05 bps |
| 2026-01 | +11.67% | 1.0% | 86.6% | +0.91 |
| 2026-02 | +9.30% | 8.2% | 81.0% | −1.09 |
| 2026-03 | +5.03% | 20.2% | 68.2% | −1.76 |
| 2026-04 | **+4.48%** | 23.2% | 56.0% | −3.45 |
| 2026-05 | +7.32% | 13.4% | 76.4% | −1.51 |
| 2026-06 | **+15.33%** | 4.8% | 70.6% | +1.75 |
| 2026-07 | +9.95% | 6.0% | 83.4% | −0.53 |
| 2026-08 | +10.52% | 9.0% | 67.2% | −1.48 |
| 2026-09 | +7.51% | 14.6% | 66.2% | −2.09 |

**Mean +9.5%/yr, min +4.5%, max +15.3%, positive in 10 of 10 windows.**

**Why it is reliable:** 56–87% of hours sit *exactly* on 0.00125%/hr, HL's hard-coded interest-rate
floor (funding = premium + clamp(interest − premium, ±0.05%)). The carry is mostly a venue constant,
not HYPE-specific crowding — which is why it survives regime changes, and also why it is not an
"edge" anyone is hiding. It applies to every HL perp.

**Arithmetic against the wall:** carry = 0.108 bps/h = 2.6 bps/day. A 9.28 bps taker round trip
amortises in **3.6 days**. Net of a ~23 bps two-leg round trip, a 30-day hold nets ~6.7%/yr and a
90-day hold ~8.6%/yr. **This is the only structure measured here whose expected return exceeds its
transaction cost.**

⛔ **It must be delta-neutral.** HYPE's annualised vol is ~70–82%. A naked short collecting 9.5%/yr
against 70% vol is a Sharpe-0.14 lottery, and the 21-month tape carries **+187%/yr drift against
you**. The carry is only harvestable hedged.

✅ **The hedge exists on HL itself** — no cross-venue leg needed, which matters because HYPE has no
Binance listing. The spot pair tracking the perp (mid 83.28 vs perp 83.148) turns over **$117M/day**,
ample at our size.

> ⚠️ **Verify the spot asset by index, not by name — VENUE.md must confirm this before anything is
> costed.** The HL spot universe returned **multiple imposter tokens literally named HYPE** with
> ~$93/day volume, while the genuine $117M/day pair resolved under a *different* name in the
> `spotMetaAndAssetCtxs` token map. This is the ghost-quote lesson in a new costume: tape-gate the
> instrument, not the label. I am ~85% confident the right leg is spot index `@109`; that last 15%
> is a venue-agent question, and the carry recommendation is contingent on it.

Open, and not mine: HL spot taker fee (my 23 bps round-trip assumed ~7 bps/side on spot), spot
borrow/holding cost, and whether the position is margin-efficient in one account.

---

## 6. Provenance and what would change my mind

**Rests on 100.2 hours / 4 days / one regime** (2026-09-13 14:49 → 09-17 18:59 UTC): every spread,
slippage, adverse-selection and realised-vol number. 1.91M bbo, 1.21M trade legs, 67k l2Book
snapshots (5.39 s cadence — too coarse for queue dynamics, adequate for quoting).
**Rests on 11 months:** the funding table only.
`hl-hist` had not landed when I ran; nothing here uses it.

**Data-quality flag for DATA.md:** trade-tape notional reconciles to `dayNtlVlm` at a ratio of 1.93x
in one hour and 4.96x in another. The tape is not double-counted in a simple way (repeated hashes are
genuine multi-level sweeps), but the venue counter and the tape do not agree and I could not close it.
All fill rates quoted here inherit that uncertainty; the *sign* of every conclusion does not, because
optimistic fill rates flatter the maker.

**What would reopen this:**
- A maker rebate ≥ **+0.4 bps** *and* evidence adverse selection has fallen below 0.36 bps — both
  required; today's deepest HL tier (−0.3 bps at >3% venue maker volume) still leaves −0.06/fill.
- A 1-hour signal with **demonstrated OOS IC ≥ 0.10**, which would be ~3x anything in this codebase.
- Funding turning negative for a sustained window — it has not in 11 months, but April 2026 reached
  +4.48% with 23% of hours negative, so the carry is not a constant and should be monitored, not assumed.

**What I would not spend another day on:** sub-minute microstructure on HYPE. The bound in §3 does
not depend on any model I could build.

*Deploy decisions are the user's; nothing here is a deployment proposal.*
