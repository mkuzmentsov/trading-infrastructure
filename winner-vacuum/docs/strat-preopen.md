# Pre-open trading (bids AND mint-asks). VERDICT: DEAD both directions — pre-open flow is INFORMED.

Idea (user, 2026-08-13): trade before the bar opens — "no strike yet, fair
≈0.50, no adverse selection". Data: 5m mrec recorders capture next1-3 roles
= pre-open books AND `trd` prints, ~7 days × 2,024 outcome-labelled bars.

## ⚠️ THE SCANNER BUG (method lesson, cost us a wrong verdict for ~2h)
First scans prefiltered lines on `'"trd": [['` (with space); raw mrec JSON is
compact `"trd":[[` → the filter matched NOTHING → "zero pre-open prints" →
I built a clean mechanical story ("nobody holds inventory pre-open so no
sell flow CAN exist") on top of a broken measurement. The probe without the
prefilter had already seen 1,110 pre-open prints. **Rule: never accept a
zero-count without histogramming raw data first; a tidy mechanism story
makes a bug MORE convincing, not less.**

## Corrected numbers (7d, 2,024 bars, btc 5m)
Pre-open flow is huge and 50:1 buyer-dominated: 129,191 BUY prints vs 2,498
SELL prints. Price mass: buys concentrated 0.30-0.50, sells sparse.

| strategy | levels | result |
|---|---|---|
| Rest BIDS both sides pre-open | 0.48 / 0.49 | pair-bars 8-12, solo-bars 204-295, **−$121 to −$145/day** — the thin sell flow that exists hits the side that goes on to LOSE (adverse even pre-open) |
| MINT + sell both sides (asks) | 0.50 / 0.51 | both sides sell in 92%/53% of bars — but **−$195 / −$199/day** |
| deeper asks | 0.52 / 0.53 / 0.55 | **−$705 / −$492 / −$365/day** (worse closer to the flow) |

## Root cause (measured, not assumed this time)
Pre-open buyers preferentially buy the side that ends up winning — prior-bar
drift information leaks into the next bar. "No information pre-open" is
FALSE. Both resting directions are the informed flow's counterparty.
Historical echo: pm-rebates-farmer (a pre-open 50/50 two-sided farmer,
decommissioned 2026-07-09) bled the same way ("single-fills the drag").

## Combinations NOT tried (and why not)
- Pre-open asks above 0.55: fills thin toward zero while one-sided keep-risk
  persists; the level curve is monotonically less bad but still negative at
  0.55 — extrapolation unfavorable, marginal value only.
- Pre-open on 15m/1h series: same buyer-dominated structure (mechanism is
  series-independent); untested numerically — revisit only with a concrete
  reason to think the informed-drift effect is absent there.
