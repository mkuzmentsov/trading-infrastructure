# Bar autopsy — `btc-updown-5m-1789393200` (2026-09-14 13:40–13:45 UTC)
**Built 2026-09-14 with `.claude/skills/pm-bar-dash`. Nothing deployed, no bot config touched.**
Dashboard: <https://claude.ai/code/artifact/345f5625-5b5b-4292-a438-9353a6e9ce16>

**−$20.80 on one clip — btc's entire loss for the day** (8 fills, 7 wins, day net −$18.96;
without this bar btc closes **+$1.84**). It is the second loss bar autopsied in two days and it
points at the *same* lever as the first, from the opposite direction — which is why it is worth
writing down, and exactly why it must not be treated as evidence.

## 1. The bar

| | |
|---|---|
| strike / final (`PF_TE_VERIFY`, err **0.0 bps** both) | 78089.9115 → 78090.3997 |
| margin | **+0.0625 bps** → **UP** |
| our fill | **DOWN**, displayed ask 0.79, **filled 30.76 sh @ 0.6762**, $20.80 |
| result | **−$20.80** (ledger) / **−$21.27** net of the taker fee |
| market | 3,110 prints, $45.5k notional |

**+0.0625 bps** is the thinnest margin in anything we have autopsied — six hundredths of one
basis point over a 60-second average.

⚠️ **Our own recon gets the SIDE WRONG here: −0.0836 bps (DOWN) vs the venue's +0.0625 (UP).**
`fobs` is **53 of 59** — the recorder missed six Chainlink ticks in the final window
(`−58, −56, −54, −50, −48, −25`). This is [[binance-chainlink-divergence]]'s "unlabelable slice"
made concrete, and it is the case gotcha 3 of the skill exists for. `build_dash.py` preferred
`PF_TE_VERIFY`, which is why the dashboard is right.

## 2. Why it lost — and this time it is NOT an estimator artefact

The live H1 at the fire was **−1.947 bps off 35 real ticks** (reproduced to the digit from
`cl.parquet`). That was an *honest* read. BTC then rallied and dragged the average across zero:

```
tl 20   cl −1.91 bps      H1 −1.947   ← FIRE, bought DOWN
tl 19   cl −1.87          H1 −1.936
tl 18   cl +1.68  ← +3.5 bps in ONE second
tl 14   cl +5.97          H1 +0.217
tl 13   cl +6.62          H1 +0.356
close                     H1 +0.049   (venue +0.0625)
```

Unlike the doge bar, nothing about the forward-fill was to blame — the estimator was reporting
what had actually happened. **The information that killed it was in a different feed.**

## 3. ⭐ Binance had the whole move at the fire instant

Raw `bookTicker` (never bucketed — skill gotcha 1):

| tl | Binance dev vs strike |
|---|---|
| 30 → 22 | +1.81 … **+2.06** (flat) |
| 22 → 20 | **+2.06 → +6.93** ← the move |
| **19.87 (the fire)** | **+6.93 bps** |
| 18 → 16 | +7.70 → **+10.74** |

At the moment the bot bought DOWN, **Binance said +6.93 bps and the Chainlink tick it was using
said −1.87 — an 8.8 bps disagreement**, and Binance had already been there for ~2 seconds.

Counterfactual, filling H1's 18-second unobserved tail with the live Binance deviation instead of
the stale Chainlink tick:

| tail filled with | H1 | vs `eff_thresh` 0.707 |
|---|---|---|
| **Chainlink last tick, −1.91 bps (what it used)** | **−1.946** | fires DOWN → **−$20.80** |
| Binance **at** the fire, +6.93 bps | **+0.704** | **no fire** (and any fire is UP, the winner) |
| Binance 2 s earlier, +2.06 bps | −0.755 | fires DOWN |
| the tail that actually happened | +0.049 | — |

## 4. The sweep was a falling knife, not a windfall

One 10 Hz row before the fire the DOWN book was **0.98 / 0.99 with 4,175 shares** on the ask.
110 ms later it was **0.83 / 0.86 with 60**. It kept going: 0.31/0.57 by tl 16.7, **0.11/0.14** by
tl 15.

The bot's `seen_ask` was 0.79 and it sent a **dollar-denominated** $20.80 FAK at limit 0.80. It
filled **30.76 shares at 0.6762** — 14¢ of "price improvement" — and `PF_TE_TOXIC_BRAKE` fired on
exactly that improvement, correctly closing the bar to further clips, but only after the fill.

⭐ **This is the documented bad-sweep class, not the good one.** [[btc-live-fill-ledger]]: sweeps
from a displayed **≥0.98 = +$37.46**, sweeps from a displayed **≤0.90 = −$4.52**. This was a sweep
from **0.79**. The dollar-FAK's great strength — it buys *more* when the book is cheap — is
precisely what makes it expensive when the book is cheap *because the market just learned
something*. [[taker-side-adverse-selection]] said this in general; here is the receipt.

## 5. The bid-drop veto blocks this one too

[[bid-drop-veto]] / `strat-losstail-veto-20260910` §9 — SHIP verdict, still **absent from the pods**
(no `PM_TE_BIDDROP*` in the btc env). On the favourite's (DOWN) own bid:

```
seen_ask 0.79 < MAX_ASK 0.98          → in scope
dB6  = −0.140   (DOWN bid 0.96 → 0.82)  ≤ −0.01 → BLOCK
dB10 = −0.080                            ≤ −0.01 → BLOCK
dB20 = −0.120                            ≤ −0.01 → BLOCK
```

All three windows fire, and unlike the doge bar it is **not** anchor-sensitive — the bid had been
falling for 20 seconds. **Two loss bars on two consecutive days, both caught by a rule that has
been sitting at SHIP for four days.**

## 6. What this is NOT

- **It is not evidence.** Both autopsied bars were selected *because they lost*. Two anecdotes
  where a lever would have helped tells you nothing about what it costs on the bars it would also
  have blocked. [[vacmaker-analytics-leads]] and the 09-14 hunt both exist because of this trap.
- **It does not re-open [[latency-ceiling-closed]]** — but it is not what that closed, either.
  That ceiling priced *"receive the Chainlink ticks that exist, with zero relay lag"* at $0.67/day,
  and explicitly found **~99% of gated error is unobserved FUTURE ticks**. Projecting the
  *unobserved tail* from a leading venue is a different object, and it is the 99% the ceiling set
  aside. Do not cite the ceiling to dismiss it, and do not cite these two bars to fund it.
- **The §37 delay is not the culprit**, though it is uncomfortable here: the book was 0.98/0.99×4,175
  until T−20.81 and the gate released the fire 0.9 s later into the collapse. At ~30:1 payoff a
  single bar carries no information about that gate — logged so nobody re-derives it.

## 7. The measurement this actually deserves

A tail-freshness veto is measurable on the **pod ledger with no fill model at all**, exactly as the
bid-drop veto was: a veto only ever *removes* a fire, and each fire's real PnL is already recorded.
Rule shape: at fire time, compute the live Binance deviation and the Chainlink tick the bot is
about to forward-fill; veto when they disagree beyond some margin **and against the fire's side**.

⚠️ **The binding constraint is tape, not method.** `brec` (Binance) only went live **2026-09-13
~17:40 UTC**, so barely a day of it exists. But the recorder's own `SNAP.spot` / `lead_bps` fields
are 10 Hz and go back as far as the pods' 7-day retention — that is the join to build, against
`PF_TE_WHALE_ORDER` fires. Until that runs, this document is two anecdotes and a mechanism.

## 8. Reproduce

```bash
cd <repo root> && source ./.dev-env-source
python3 .claude/skills/pm-bar-dash/build_dash.py btc btc-updown-5m-1789393200 --outdir <scratch>
python3 .claude/skills/pm-bar-dash/assemble.py <scratch>/dash.json <scratch>/bar.html
```
