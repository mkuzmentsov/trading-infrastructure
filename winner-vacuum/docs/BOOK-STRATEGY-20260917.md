# The book: a professional strategy, designed at target scale and run small
**2026-09-17. A design document, not a research result. Nothing here is deployed.**

Every agent round so far has hunted **alpha**. That is not what a professional does with $467. At
this size a desk's edge is **cost, sizing, abstention and survivorship** — and the strategy should be
**designed correct at the scale it would matter, then run scaled-down as validation.**

## 0. Diagnosis — the two structural facts that determine everything

> **1. The Polymarket fleet does not scale with capital.** It is limited by the *book*, not the
> bankroll: the favourite shows a takeable ask on only **3.3% of seconds at tl 0-14**. It already
> turns **$1,748/day of stake on $467 of equity**. Adding capital buys nothing.
>
> **2. The HL funding carry is the only thing here that does scale** — to roughly **$50k** on ten-level
> depth, mechanically, at ~7%/yr.

⇒ **The allocation rule follows immediately: the fleet gets a fixed, small, capped allocation; every
marginal dollar above it goes to carry.** That is the whole capital policy, and it is not a
judgement call — it is forced by capacity.

| carry capital | $/yr | $/day |
|---|---|---|
| $1,113 (minimum viable) | +$80 | $0.22 |
| $5,000 | +$360 | $0.99 |
| $20,000 | +$1,440 | $3.95 |
| $50,000 (depth ceiling) | +$3,600 | $9.86 |

⚠️ **And the honest consequence: at today's size the sleeves do not diversify.** A $5k carry against
the fleet moves daily t from 0.233 to 0.257. **The portfolio effect only becomes real above ~$20k.**
Below that this is one book with a hedge attached, and should be described that way.

## 1. The book — three sleeves, each with a job

**Sleeve A — CARRY (the engine).** HL delta-neutral funding carry: long `@107` HYPE/USDC spot, short
HYPE perp. ~7%/yr net of the measured 22.08 bps round trip, break-even hold ~8 days. This is the only
**mechanical** edge we own — 66% of hours pinned at a venue-defined floor, 22 of 22 months positive.
*Role: the return engine, and the only sleeve that deserves incremental capital.*

**Sleeve B — FLOW (the fleet).** The PM 5m vacmaker, run at **k ≈ 0.5**. Capped, capacity-bound, and
unproven at t = 1.25. *Role: an option on an edge we have not yet disproved, held at a size where
being wrong is survivable.* Not a return engine — a research position with a P&L attached.

**Sleeve C — RESERVE (dry powder).** Idle USDC. At our size this is not laziness: carry entry is
cheapest when funding spikes, and the short leg must be defendable through a **7-day unstaking
queue**. *Role: margin defence and the ability to size into dislocation.*

## 2. Risk framework — what actually gets managed

**Position level.** Size to a **volatility contribution**, never to a dollar. Sleeve B's clip is
`max(5, int(0.5·req_sh))` — shares, with the venue's hard 5-share floor. Sleeve A's perp leg runs at
**≤2× leverage** (3× carries a 19.6% 90-day ruin; 10× liquidates on **28% of individual days**).

**Portfolio level — a pre-committed drawdown ladder, not a judgement call:**

| peak-to-trough | action |
|---|---|
| −10% | halve Sleeve B |
| −20% | Sleeve B off; carry continues (it is delta-neutral, it does not care) |
| −30% | flat everything, mandatory written review before re-entry |

**Venue level.** PM and HL are **separate credits**, and HL is worse than it looks: staked HYPE,
trading collateral and the venue are **one credit** — a solvency event impairs all three at once and
locks the queue. Cap any single venue at a pre-set share of net worth, and **never stake** while the
carry is live: it forfeits 5% of fees but preserves the exit.

**Execution level.** Trade from the **master**, not the sub (4% off every fill, both sides). Enter
the carry with **maker** legs where patience allows — but do not book the saving in advance; resting
fills are adversely selected and this program has measured that cost.

## 3. The macro layer — and what it is honestly for

⚠️ **Macro is not alpha here.** News trading at 4.5 bps on a $467 book is a donation. Its job is
**gating and regime awareness** — deciding *when not to be on*.

**(a) Scheduled-event gating — the one genuinely untested idea.** FOMC (8/yr), CPI (12/yr), NFP
(12/yr), plus crypto-specific events. ⚠️ Note carefully: **this is NOT the vol gate that was already
refuted.** The retest killed *realised-vol* gating (hi-vol cells at t = −0.14, and §37 stripped the
vol condition). **A calendar is known in advance; realised vol is contemporaneous. They are different
variables** and the calendar version has never been tested. Testable today on the 29-day ledger.

**(b) Funding regime — an unpriced risk in our only real edge.** All 22 positive months are a **bull
regime**. Funding is mechanically leveraged-long demand; in a sustained bear it inverts and the carry
reverses sign. Mitigation is structural (the position is delta-neutral, so you simply stop) but it
needs a **pre-committed rule**, e.g. *trailing 7-day mean funding < 0 ⇒ unwind, do not average in.*

**(c) Asset-specific calendar.** HYPE unlocks and vesting, HLP drawdowns, HL protocol changes,
exchange incidents. For a carry book these are **basis** risks, and basis is already the dominant one
— daily basis-change sd is **11.4 bps ≈ 4× the daily carry.**

**(d) The $100 tick cliff.** Not macro, but the same category: a **known, scheduled-by-price** regime
change sitting **20% away** that invalidates every microstructure number we hold.

## 4. Running a portfolio on a single coin

The user's question, and it has a real answer: **decompose one asset into independent exposures.**

| exposure | accessible? | our access |
|---|---|---|
| **carry** (funding) | ✅ | Sleeve A — mechanical, measured |
| **basis** (spot vs perp) | ✅ | the risk we carry, not yet an edge |
| **direction** | ⛔ | foreclosed: a perfect 1s oracle earns 0.003 bps |
| **volatility** | ⛔ | no options on HL |

⇒ On a single coin we own **one** tradeable exposure and are short one risk. Everything else is
narrative. The portfolio discipline that remains is **time diversification** — ladder carry entries
across days rather than one clip, since funding is the return and it accrues hourly regardless of
entry timing, so there is no reason to take basis-timing risk in one shot.

## 5. Operating cadence

**Daily:** realised stake vs target; funding sign and 7-day mean; basis vs entry; margin ratio on the
short leg; drawdown against the ladder.
**Weekly:** per-sleeve attribution; process metrics (fill rate, realised cost per round trip vs
model); calendar for the week ahead.
**Monthly:** the decision gates below.

**Judge on process, not PnL.** Detecting $4/day against a $35.93 sd takes **~633 days**. Anything
judged on P&L inside a quarter is being judged on noise. Countable in days instead: realised cost per
round trip vs the 9.0/22.08 bps model, fill rate at the quoted price, stake vs target, and post-halt
leakage.

## 6. Decision gates — written now, so they are not rationalised later

1. **Fleet:** if still at **t < 1.5 after 60 more days**, the $8.37/day was 29 days of luck. Retire it.
2. **Carry:** fund at the **first** capital increment above the fleet's capped need. It is the only
   mechanical edge and it is the only sleeve that scales.
3. **Scale-up trigger:** the portfolio argument does not exist below **~$20k**. Until then, run both
   sleeves as validation and do not pretend the diversification is real.
4. **Kill:** any sleeve whose *process* metrics drift from model — regardless of P&L.

## 7. What I would test next, in order

1. ⭐ **Calendar gating on the 29-day PM ledger** — do losses cluster around scheduled macro releases?
   Distinct from the refuted vol gate, cheap, and it is the user's macro question made falsifiable.
2. **Funding-regime conditioning** — how does the carry behave in the 6.6% of negative-funding hours,
   and is a trailing-mean rule better than always-on?
3. **Basis at tick resolution** — requires adding `@107` to `hrecSubs`. Basis is the carry's dominant
   risk and is currently unobservable intraday.
4. **HL↔Bybit lead-lag** — the one unexplored edge lane, now that the listing is known to exist.
