# zec 5m — the wide book (2026-09-13). Split-and-sell DEAD; naive wide-book buying DEAD; one marginal cheap cell alive-but-thin. ⭐ zec is now RECONSTRUCTABLE (Chainlink feed exists).

Trigger: user saw the PM UI quoting **Up 71¢ / Down 95¢** on `zec-updown-5m`
(ask-sum 1.66) and asked (a) can we abuse it, (b) can we split and sell both
at those prices. Measured on the local zec v2 tape: **259 files, 3,046
labelled bars, 09-01 → 09-12**.

## ⭐ NEW CAPABILITY: zec has a Chainlink feed now
`cl`/`cl_ts` present in **100%** of 169,994 snaps (previously zec+hype were
`spot:0.0, lead_bps:null`, "no offline recon possible" — that note is now
obsolete for zec). Recon side-accuracy at tl≤14 vs RES:

| \|margin\| | n | side accuracy |
|---|---|---|
| <1 bps | 83 | 50.6% |
| 1-3 | 169 | 72.2% |
| 3-10 | 609 | 91.6% |
| **≥10** | **2,110** | **99.5%** |

Same settlement arithmetic as the other coins — zec is a legitimate
research/trading target for the first time.

## ⛔ Split-and-sell at the displayed prices — arithmetic loss
The pair is ONE book (`ua ≡ 1−db`), so the two UI asks imply
UP bid 0.05 / DOWN bid 0.29. Mint $1 (splitPosition on the
CtfCollateralAdapter) → **sell both into bids for $0.34**.
Tape-wide: ask-sum median 1.51 ⇒ **bid-sum median 0.49**. Minting to sell is
a guaranteed −50…−66¢ per dollar. The only paying variant is RESTING both
asks (mint $1, sell at 0.76/0.79 = +55%) — needs both sides lifted, but the
tape shows **~306 late-window prints across 3,046 bars (0.1/bar)** and a
one-sided fill leaves you holding the loser: that is
[strat-ask-ladders](strat-ask-ladders.md) (−$880…−$2,618/day) with no flow.

## ⛔ Naive "wide book ⇒ free money" — negative
Buy the recon-favoured side at any displayed ask ≤0.99 (|margin|≥3bps,
tl≤14): **n=144, accuracy 81.2%, avg ask 0.93 ⇒ −11.7¢/share.**
Accuracy collapses 99.5% → 81.2% exactly when an ask exists — bug #20
(condition on BUYABILITY) reproduced on a brand-new coin. The wide spread is
not generosity; the offer appears when the market disagrees with us.

## 🟡 The one positive cell — thin, episode-dependent
Winner-side ask **≤0.95** at |margin|≥3bps: n=23, accuracy 82.6%,
avg ask 0.60, **+21¢/share**, ~2 bars/day, median displayed 20sh (~$12).

| day | n | PnL @ displayed size |
|---|---|---|
| 09-01 | 1 | +$0.53 |
| 09-06 | 2 | +$2.07 |
| 09-07 | 2 | +$0.76 |
| 09-08 | 4 | +$8.12 |
| 09-10 | 1 | +$4.63 |
| **09-11** | 6 | **+$52.45** |
| 09-12 | 7 | −$6.17 |
| **total** | 23 | **+$62.38** (6/7 days positive) |

⚠️ **84% of the total is ONE day** (09-11); ex-best-day **+$9.93 over 6 days
≈ $1.65/day**. That is the §45/§46/§47 fingerprint (a seam that is really
1-2 episodes). Takeability is better than feared but unproven: **13/23** of
these bars saw at least one late-window print.

## Verdict / options
- Split-and-sell: **closed, arithmetic** — do not revisit.
- Wide-book buying at face value: **closed** (−11.7¢/sh).
- Cheap cell: **marginal**. Realistic expectation ≈ **$1-2/day gross before
  the fill haircut**, ~2 opportunities/day at ~$12 displayed. Below the
  fleet's noise floor, but the infrastructure cost is ~zero (twapedge
  supports any coin; a zec pod is one yaml + one helm install) and the
  novelty is that zec is *uncontested* — the "informed maker pulls" wall may
  be weaker where nobody is trading.
- If piloted: MIN_ASK ≈0.95 (NOT the 0.55 fleet default — the ≤0.99 band is
  measurably negative here), decisive-margin gate ≥3bps (prefer ≥10bps where
  accuracy is 99.5%), $5-12 clips, own daily halt, judge on fill rate first.
- **NOT deployed** — live deploys need explicit user confirmation.

Method note: fire = first snapshot at tl≤14; ask taken from that snapshot
(not a first-touch path replay), so treat the cell EV as an upper bound.
