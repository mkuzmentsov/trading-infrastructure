# strat-reversion — buy the dip for the occasional reversion (the mean-reversion bot)

**Question (user, 2026-08-23 ~17:30 Kyiv):** ignore the running bots — build the
*opposite* of vacmaker. Vacmaker protects itself against bars that revert; make
a bot that BUYS those reversions: take the cheap (losing) side and hold.

**VERDICT ⛔ — it cannot be built, and this time the wall is the PRICE, not the
fill.** Reversions are real and frequent; they are also correctly priced or
over-priced at every price, at every moment of the bar, on every coin, on every
day. Buying the losing side is −15.7% of stake pooled over **119,408
observations**, and the best cell that exists anywhere is −3.8%.

---

## The dataset — why this is the definitive test

`tools/revcal.py` on the local archive (`every-tick-single/data/mrec/`),
**2026-07-30 → 08-17, 7 coins, 28,422 bars, 376,002 (bar × time) observations**
on a 20-point tl grid from T−270s to T−3s.

There is **no estimator anywhere in it.** The book prices are what the venue
displayed and `RES` is the venue's own settlement label, so "what did the losing
side cost and how often did it win" contains no recon, no Binance proxy, no fill
model, and no fee assumption (results are gross — a fee only makes them worse).
That is why it can close a question that §27 (15.7k obs, 1¢ only, tl≤30) and
§29 (2,668 probes, one cell) could only close locally.

## 1. The dog is over-priced at EVERY price and EVERY moment

EV as % of the price paid, dog bought at its ask, held to redemption:

| dog ask | tl=10 | tl=20 | tl=30 | tl=60 | tl=90 | tl=120 | tl=180 | tl=240 |
|---|---|---|---|---|---|---|---|---|
| 0.02–0.05 | −47.9 | −57.4 | −43.4 | −27.6 | −42.8 | −33.0 | −24.9 | — |
| 0.05–0.10 | −43.2 | −39.5 | −26.5 | −28.2 | −23.2 | −22.3 | −9.4 | −19.7 |
| 0.10–0.20 | −41.5 | −34.2 | −20.3 | −19.0 | −16.0 | −19.4 | −6.0 | **+6.2** |
| 0.20–0.30 | −42.0 | −36.3 | −33.5 | −18.2 | −16.0 | −10.9 | −12.3 | −5.7 |
| 0.30–0.40 | −26.4 | −25.3 | −26.7 | −12.8 | −13.4 | −7.0 | −6.0 | −3.4 |
| 0.40–0.50 | −32.7 | −23.5 | −21.6 | −11.9 | −9.6 | −5.2 | −0.8 | −3.6 |

⭐ The structure is a **time** structure, not a price structure: the
favourite-longshot premium is enormous in the settlement window (−25…−60%) and
decays to roughly the spread early in the bar (−1…−6%). The lone positive cell
(tl=240, 0.10–0.20, +6.2%, n=2,893) has a 95% CI of 15.9–18.7% around a 16.2¢
price — it is *fair*, not cheap.

**The mirror is also negative:** buying the FAVOURITE at its ask unconditionally
runs −0.2…−4% almost everywhere (it is +EV only when a signal picks the bar —
that signal is the vacmaker's TWAP recon, §41).

## 2. The literal dip — "it just got crushed, buy it" — does not revert

For each pair of grid points (now ← 30–60s earlier), bucket by how far the dog's
price FELL in that window, then compare with the unconditional win rate at the
same price. ~150 cells. **Not one is meaningfully positive**, and the deeper
drops are usually *worse* than the shallow ones — e.g. at tl=30←60 with the dog
at ~0.05: fell 0.02–0.05 → 3.09% win, fell >0.20 → 3.22%, against a 2.90%
unconditional base and a 4.6¢ price. The market re-prices a move correctly;
what looks like an over-reaction is the crowd finding the right number.

## 3. Violence does not help either — the intra-bar path is momentum

Buying the dog immediately after the *underlying* moved violently against it
(move normalised by that coin's median move over the same window):

| tl←then | <1× move | 1–2× | 2–3× | 3–5× | >5× |
|---|---|---|---|---|---|
| 20←50, dog ~0.05 | −41.9% | −52.5% | −85.0% | −66.5% | −72.3% |
| 30←60, dog ~0.05 | −41.9% | −44.1% | −49.4% | −52.4% | −52.1% |
| 60←120, dog ~0.05 | −41.3% | +4.7% | −41.6% | −42.0% | −18.8% |

More violence = *worse*, which is the same answer the July study got from the
underlying ("a dip 0.1% below open closes back up only 13–22%;
the intra-bar path is momentum/continuation") — see [[rebate-harvest-dead]].
Two cells out of ~100 print positive (n≈263, n≈307); at that count, two is what
chance owes you.

## 4. Scalping the retrace instead of holding is worse

Buy the dog (0.05–0.35), sell at the first later bid ≥ entry+X, else ride to
redemption. n = 12k–17.6k per row:

| entry | +0.03 | +0.05 | +0.10 |
|---|---|---|---|
| tl=150 | −13.7% | −13.7% | −13.0% |
| tl=120 | −15.0% | −14.7% | −13.4% |
| tl=90 | −18.3% | −18.3% | −17.6% |
| tl=60 | −22.5% | −22.0% | −21.2% |

Only 13–31% of dogs ever retrace far enough to exit green; the rest ride to
zero, and you paid the spread to get in. (§29 found the same in the 2–5¢ cell;
this extends it to the whole bar and to every target.)

## 5. Per coin, per day, and the last stand

Dog at 0.05–0.35, tl 30–180, **n = 119,408**: true win rate **15.14%**
[14.94, 15.34] against a mean ask of **0.1795** ⇒ **−15.7% of stake**.

- Every coin negative: eth −8.4%, btc −11.0%, xrp −14.0%, sol −14.2%,
  bnb −19.2%, doge −22.2%, hype −58.9%.
- **18 of 19 days negative.** The one positive day (08-09, +9.3%) is n=718.
- The **vig** explains much of it — median `ua+da−1`: btc/eth **0.01**,
  sol/xrp 0.01–0.04, bnb 0.04–0.05, doge 0.03–0.05, hype 0.06–0.13. On a 15¢
  dog a 3¢ round-trip cost is 20% of stake.
- Best cell anywhere (early bar tl≥180, dog 0.08–0.22, n=20,782): **−3.8%**,
  stable across a train/test split (−4.3% / −3.3%), and −9.6% once the
  taker fee the code assumes (0.07·p·(1−p)) is applied. Only btc (+1.8%) and
  eth (+0.3%) are non-negative and both CIs straddle zero: in the two tightest
  books the dog is priced *fair*.

## 6. What would have to be true to revive it

Fair value in the headline cell is **0.1514**; the ask is **0.1795** (+18.6%)
and the bid is **0.1486** (−1.8%). So:

- A **taker** needs the price to come to him by ~3¢ — that is the whole edge and
  more.
- A **perfect maker fill at the dog's bid** earns **+1.8% gross** — and the
  measured resting adverse selection on this venue is −0.47¢ per fill
  ([maker-program-2026-08](maker-program-2026-08.md)), i.e. −3% on a 15¢ option.
  Even flawless queue position loses.

That is the whole case: the reversion premium the strategy needs to harvest is
smaller than the spread it must cross to get in.

## 7. Relationship to what was already known

- **§27** (1¢ reversal lottery, tl≤30) and **§29** (dog in the weak-est cell) —
  same conclusion, tiny slices. This supersedes both with 24× the observations
  and full-bar coverage, and adds *why*: the premium is a decaying function of
  time-to-close, so the settlement window §27 measured is its worst region.
- **§41** (`strat-dipbuy.md`) is the *other* dip: buying the recon-implied
  WINNER cheap. That one has a real edge and is already deployed; it dies only
  on fill rate. This one has no edge to fill.
- The two together close the "buy cheap" family from both ends: the cheap side
  we are right about is unfillable, and the cheap side we can fill is the side
  we are wrong about.

**Do not reopen** without one of: sub-cent pricing on this venue, a maker
primitive that dodges the −0.47¢ wall, or a coin whose vig is ≤1¢ AND whose
dog is measurably under-priced (btc/eth are the only ≤1¢-vig markets and their
dogs are fair, not cheap).
