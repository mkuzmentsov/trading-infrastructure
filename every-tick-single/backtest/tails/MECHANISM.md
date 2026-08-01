# Why fill rate cannot be "solved" — the coupling, measured

Everything tried, in one place, same units (per share-pair, per bar).

| regime | when you quote | any-fill rate | single-fill cost | net/bar |
|---|---|---|---|---|
| **pre-open** (`next1`, bar not started) | no information exists | **8.3%** | **−0.0135** | −0.0005 (flat) |
| live bar, t−150s | information flowing | **92.7%** | −0.0844 | −0.0125 |
| live bar, t−150s, −8c deeper | " | 92.4% | −0.2478 | −0.055 |
| post-close 0.99 (**the vacuum**) | outcome KNOWN | ~8% of bars | n/a | **+0.01/share** |

## The coupling

Adverse selection and fill rate are driven by **the same variable**: how much
information is in the market at the moment you are hit.

- **Pre-open**, nobody can be informed, so a fill costs only the spread —
  single-leg unwind is **−1.35c**, six times cheaper than mid-bar. But almost
  nobody trades: 91.8% of bars produce **no fill at all**, and both legs fill
  on 1.1%. Safe and empty.
- **Mid-bar**, flow is everywhere — 92.7% of bars fill at least one leg — but
  the person hitting you knows where the price is going, and the single-leg
  cost rises to **−8.4c**.

You cannot pick a time that has one without the other. Quoting earlier buys
safety and loses flow at almost exactly the rate that cancels it. That is why
every variant lands within ~1c of zero and on the wrong side of it.

Measured proof that this is not a latency problem: cutting reaction time from
1.0s → 0.3s → 0.1s recovers **0.4c of the 8.4c** single-fill cost.

## The one exception, and what it teaches

The vacuum breaks the coupling because it quotes in the only regime where
**flow is high AND information is zero**: after the bar has closed but before
it resolves. The outcome is already determined, so the seller hitting our 0.99
bid cannot know more than we do — they are releasing capital. Fill rate ~8% of
bars at +1c/share, and it is the only positive number in this document.

So the question for any new strategy is not "how do I get filled more" but:
**where else is flow high and information zero?** Candidates not yet tested:

1. **Post-close on the OTHER coins** — same structural regime as btc, five more
   markets, no new mechanism required. The cheapest real expansion available.
2. **Post-close deeper than 0.99** (0.97/0.98) — same zero-information regime,
   worse price, presumably higher fill rate. Directly measurable from mrec.
3. **Forced/mechanical flow** — redemption sweeps, expiry-driven unwinds by
   other bots, anything where the counterparty trades for a reason unrelated to
   the outcome. This is what the 0.99 fill already is; the question is whether
   there are other such windows.

## What was tried and failed (do not re-run without a new mechanism)

- buy tails at ≤0.05 → −38% to −72% ROI, every price bucket, per-observation
- sell tails / cross for the favourite → ≈0 after fees; the mispricing IS the 1c spread
- rest a maker bid on the favourite → +1.63c/share on paper, −2.8 to −4.0pp adverse selection kills it
- two-sided maker pair, live bar → −1.25c/bar (was −8c before the unwind fix)
- two-sided maker pair, pre-open → flat, no flow
- deeper quoting → better per-pair, proportionally more singles, still negative
- faster reaction → recovers 5% of the single-fill cost
- Gaussian reversal model → predicts 22.5% where reality is 6.58%; unusable
- volatility normalisation (z = gap/σ√t) → does not separate adverse selection at all
