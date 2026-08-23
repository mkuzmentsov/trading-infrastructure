# strat-dipbuy — "the opposite of vacmaker": buy the cheap side, hold to redemption

**Question (user, 2026-08-23 ~16:00 Kyiv):** deploy the opposite of vacmaker —
a dip-buy bot that takes the cheap side and sells / holds till redemption.

**VERDICT (2026-08-23 17:0x Kyiv, no code deployed, no bot touched):**

1. ⛔ **There is nothing to deploy as a separate bot.** The dip lane is already
   running: vacmaker's `PM_TE_MIN_ASK=0.55` means every clip in 0.55–0.98 *is*
   a dip buy, and after the §37 delay they nearly all fire at tl≤20. That lane
   is the fleet's **profit centre**: ask 0.75–0.90 = **+3.98% ROI** vs +0.21%
   at >0.98, and **+$34.54 of the fleet's +$50.85** total logged live PnL.
2. ⛔ **Widening it downward (below 0.55) is refuted a second way.** §38 killed
   it on day-concentration; §41 below kills it on execution: a displayed ask
   ≤0.75 **fills 11% of the time, and the fills are the wrong ones**.
3. ⛔ **"Sell instead of holding" is strictly worse** — the book stays wide to
   the close: median exit bid at T−3 on a *winning* cheap entry is 0.86, mean
   give-up **24.9¢/share** vs redemption, and redemption returns the capital
   ~2 min after close anyway.
4. 🟡 The only live option with evidence behind it: **size up the existing
   0.75–0.90 & tl≤20 cell** (today capped at one 8–9sh clip by
   `WHALE_LADDER_MIN_ASK=0.94`). Not deployed — see §5, it is a real risk
   trade-off and this session was explicitly hands-off.

---

## §41.1 — What the offline sim says (Chainlink ground truth)

`tools/dipcl.py`, 2026-08-21 19:25 → 08-23 13:00 UTC, 7 coins, **2,603 usable
bars**. First study on the settlement stream itself (`cl`/`cl_ts`/`tw`), which
is what §38 said to wait for.

Controls: **V1** reconstructed TWAP side == venue RES on **99.54%** of bars ·
**V2** live-config replica +1.09% ROI vs the live fleet's +0.40…+1% ✓ ·
**V3** side-flipped placebo −89.7%.

One clip per bar, first qualifying instant, tl≤20, |margin| ≥ 1 bps:

| ask band | n | win% | breakeven | ROI | P(binom) |
|---|---|---|---|---|---|
| 0.10–0.25 | 2 | 0% | 20.5% | −100% | — |
| **0.40–0.55** | 23 | 87.0% | 50.3% | **+75.6%** | 0.0003 |
| 0.55–0.75 | 29 | 79.3% | 68.3% | +15.8% | 0.139 |
| 0.75–0.90 | 35 | 91.4% | 84.6% | +7.9% | 0.191 |
| 0.90–0.95 | 45 | 97.8% | 93.0% | +5.1% | 0.167 |
| 0.95–0.98 | 92 | 97.8% | 97.1% | +0.6% | 0.503 |
| >0.98 | 101 | 100% | 99.3% | +0.7% | 0.489 |

The mispricing is **real in the data** — ROI rises monotonically as the ask
falls. Mechanism: the market prices the *point* price, settlement is the
*60-tick average*; when a late move flips the point price the book re-prices
and the arithmetic does not. Supply of the decisive cheap cell (≥3bps,
0.25–0.90, tl≤20) is ~**17 bars/day fleet-wide**, but 23 of the 30 events
landed on 08-22 — it is a **volatility-supplied** lane, not a steady one.

## §41.2 — ⭐ Why it does not survive contact with the venue (`tools/fillphys.py`)

Everything above assumes a displayed ask is takeable. The pods' own logs
(3,212 FAK orders) say it is not:

| seen ask | orders sent | matched | shares filled |
|---|---|---|---|
| 0.55–0.75 | 295 | **11.2%** | 10.6% |
| 0.75–0.90 | 218 | 50.5% | 49.3% |
| 0.90–0.95 | 443 | 52.1% | 50.8% |
| 0.95–0.98 | 1292 | 43.7% | 43.3% |
| >0.98 | 963 | **75.0%** | 70.0% |

Not errors (`PF_TE_LIVE_ERR` = 0), not price (we pay `ask + LIVE_PX_BUFFER`;
every unmatched cheap order was priced ABOVE the seen ask), not size (9sh
against 40–50sh displayed). The venue simply kills the FAK in ~81–140 ms
(matched orders take ~300–390 ms).

⭐⭐ **And the fills we do get are the wrong ones — adverse selection on the
TAKER side, per bar:**

| cheapest ask attempted | bars | intended side won | attempts/bar |
|---|---|---|---|
| ≤0.75 — we filled | 42 | **71.4%** | 1.3 |
| ≤0.75 — we hammered and NEVER filled | 22 | **100.0%** | 11.5 |
| 0.75–0.90 — we filled | 97 | 89.7% | 1.2 |
| 0.75–0.90 — never filled | 28 | **100.0%** | 3.0 |

Read as: the cheap offer still standing when our order lands is the one where
the market is right and our estimate is wrong — §38's ⭐ conclusion, in
execution rather than in labels.

⚠️ **How much to trust that table (ledger #16 applies).** The NEVER column is
partly conditioned: a bar only accumulates 11 attempts while the signal keeps
holding, and a signal that holds is a signal that wins, so "100%" is an upper
bound, not a clean counterfactual. Two things are NOT conditioned and carry the
verdict on their own: the **11.2% match rate**, and the fact that the cheap
clips we do win are worth far less than the sim says (§41.3: +2.1% live vs
+15.8% simulated for 0.55–0.75). An archive-side version of the test — win rate
split by whether the same ask was still takeable 1s later — points the same way
in 0.55–0.90 (77.8% vs 100%, 80.0% vs 91.7%) but at n≈10 per cell it settles
nothing; it needs the ~3 weeks of `cl` that §38 asked for.

**Structural reason (verified on 3 coins, 31k+ rows each, 100.00% of rows):**
`ua ≡ 1 − db` and `uas ≡ dbs`. The binary pair is **one book** — "buying UP at
0.60" *is* hitting a resting DOWN bid at 0.40. A cheap ask is not an offer
somebody forgot; it is an informed maker's bid on the other side, and it is
pulled the moment the move that creates our signal becomes visible. (The same
identity is why the vacmaker's 0.99 fills exist at all: those are the §27
1¢-lottery bids on the loser side, and *those* buyers do not pull.)

## §41.3 — What the live cheap lane actually earns

`tools/fillphys.py`, all 7 pods, 1,754 settled clips, $12,691 staked,
**+$50.85 = +0.40% ROI**:

| ask band | n | win% | PnL | ROI |
|---|---|---|---|---|
| ≤0.55 | 6 | 50.0% | +$2.79 | +7.3% |
| 0.55–0.75 | 44 | 70.5% | +$5.47 | +2.1% |
| **0.75–0.90** | 126 | 88.9% | **+$34.54** | **+4.0%** |
| 0.90–0.95 | 202 | 93.6% | −$9.60 | −0.7% |
| 0.95–0.98 | 524 | 97.1% | +$4.92 | +0.1% |
| >0.98 | 852 | 99.1% | +$12.74 | +0.2% |

The cell **ask 0.55–0.90 & tl≤20**: n=70, win **88.6%** vs 79.1% breakeven,
+$53.87 on $479 staked = **+11.24% ROI**, P(binom)=**0.029**. Robustness — the
test that killed §38's survivor — holds here: leave-one-day-out ROI stays
**+9.3% … +14.9%** across all 5 days (08-19 → 08-23), and it is positive on
5 of 7 coins (bnb n=3 and doge n=9 negative). ~14 clips/day, ~$96/day staked,
≈ **+$10/day**.

Note the offline↔live gap: the sim says +15.8% for 0.55–0.75, live says +2.1%.
That ~7× is the fill physics above, and it is the reason the 0.40–0.55 cell's
+75% must be read as **unreachable**, not as money on the table.

## §41.4 — Sell, or hold to redemption?

Hold. For cheap entries (ask ≤0.90, |m|≥1bps, tl=20, size≥5) that go on to
**win**, the best bid still available at T−3 is p10 0.49 / **p50 0.86** / p90
0.99 — mean give-up **24.9¢/share** against a 1.00 redemption. The wide book
that creates the entry never closes before the bell. Capital is not the excuse
either: `PF_TE_LIVE_SETTLE` lands ~**2 min after close** (sample: ws+424s), so
selling early buys back less than half a bar of a $95 bankroll.

## §41.5 — The one deployable option (NOT deployed)

Raise the clip in the proven cell only: **ask 0.75–0.90, tl≤20, decisive
margin**. Today `WHALE_LADDER_MIN_ASK=0.94` allows the ladder's 2nd/3rd clip
only at ≥0.94, so the best cell is capped at a single 8–9 share clip while the
+0.2% sink at >0.98 gets the $16 ladder.

- Upside: the cell staked ~$96/day at ~+11%; a 12–16 share clip would add
  roughly **+$5…+10/day** — *if* depth and the 50% fill rate hold (29% of
  cheap clips are already partial, so displayed depth overstates what is
  reachable; assume sub-linear).
- Cost: the loss tail doubles. One loss at 0.80 × 16sh = **−$12.8** against a
  **$15/day halt** — a single bad bar would end the day fleet-wide.
- Contraindication: §26's 0.94 ladder floor exists *because* mid-band ladder
  clips caused all 3 of that day's loss bars — though that was the tl 21-30
  era, which §37 has since closed.

**Recommendation:** if anything, a modest tilt (12sh, not 16) in that one cell,
and only with the daily halt raised proportionally or the ladder budget
re-cut — otherwise leave it. This is a risk decision, not a research finding.

## Open / re-test later
- The 0.40–0.55 cell is real in the data and unreachable by FAK. The only
  thing that could reach it is resting a bid *before* the move — which is the
  closed maker program (`maker-program-2026-08.md`) and the §16 GTC-rest
  refutation. Do not reopen without a new execution primitive.
- Re-run `tools/dipcl.py` after ~3 weeks of `cl` accumulates (§38's ask) —
  §41.1's supply/vol dependence deserves more than 42 hours.
