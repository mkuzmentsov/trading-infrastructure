# mintsalvage — what it is, what it earns, and how to make it better

Written 2026-08-04 (overnight), after ~18 hours live across six coins.
Everything below is measured: live trade record where possible, the 4,849-bar
mrec calibration set otherwise. Numbers that are estimates say so.

---

## 1. The strategy, stated precisely

Per 5-minute bar:

1. **Mint** a pair for $N through the pUSD collateral adapter (N UP + N DOWN).
2. **Hold the winner** to redemption ($1.00/share).
3. **Sell the loser at 1¢** in the closing seconds.

Per share: `+$0.01` if we identified the loser correctly, `−$0.99` if not.

Two identities worth keeping in mind, because they explain most of the
behaviour:

- **Selling the loser at 1¢ ≡ buying the winner at 99¢.** The book is
  complementary-unified (`ub = 1 − da` at equal size in every recorded
  snapshot), so this is the vacuum's trade sourced from the other side.
- **The mint is not the edge.** It is a device for manufacturing the position
  without queueing behind the ~4,265-share wall that sits at 0.99. We create
  both legs and offload the one nobody is competing to sell.

## 2. Where the edge comes from — and it is one thing only

**The 1¢ minimum tick.** When the true probability that the trailing side wins
is 0.1–0.5%, its fair value is 0.1–0.5¢ — but the venue cannot quote below 1¢.
Selling at the floor is therefore selling at 2–10× fair value. That gap is the
entire edge.

This has a hard consequence: **selling higher does not earn more.** If the
loser trades at 5¢, the market is pricing a 5% flip and the sale is EV-zero by
construction. Every cent above 1¢ is fairly priced; only the floor is not.

So the objective function is narrow:

```
EV per filled share  =  0.01 − p            (p = true flip probability at sale)
EV per placement     =  fill_rate × (0.01 − p)
```

Break-even is `p = 1%`. Everything worth doing either lowers `p` at the moment
of sale, raises `fill_rate`, or multiplies the number of placements.

## 3. What 18 hours of live trading measured

**Realised sale prices** (19 sales, on-chain trade record):

| executed at | share |
|---|---|
| 1.0¢ | 84% |
| 1.1¢ | 5% |
| 3.0¢ | 11% |

Volume-weighted **1.23¢**. The marketable-limit design already harvests richer
bids when they exist — posting at 2¢ instead would forfeit the 84%.

**Fill rate by lead size** (n=23, thin but monotone):

| \|lead\| | fill rate |
|---|---|
| 8–10 bps | 17% |
| 10–15 bps | 12% |
| 15+ bps | 0% (0 of 3) |

Fills come only from bars where the outcome is still *arguable*. Nobody bids a
cent on an obviously dead corpse. This is the same coupling as `MECHANISM.md`:
**fill rate and adverse selection are the same variable.**

**Fill rate by session** — 12–17% through the quiet afternoon, **57–82%**
during the US morning (12:30–16:00 UTC). Liquidity, not our machinery, sets
volume.

**Seven reversals**, −$294 gross:

| Kyiv | coin | lead at sale | gates then in force |
|---|---|---|---|
| 01:06 | xrp | −15.6 bps @ t−90s | early tiers (removed) |
| 03:54 | sol | −4.1 bps | pre-floor |
| 10:00 | doge | +2.9 bps | pre-floor |
| 10:21 | eth | +7.1 bps | 7 bps floor |
| 17:10 | sol | −8.2 bps | 8 bps floor |
| 17:27 | btc | **−13.6 bps** | 8 bps floor |
| 18:38 | bnb | +8.3 bps | 8 bps floor |

Note the btc one: 13.6 bps, z=2.46 (nearly double requirement). **No floor
removes the tail** — it only thins it.

## 4. The two findings that matter most

### 4a. Our signal is not the problem

Disagreement between our Binance-derived lead **at the bell** and the settled
outcome, 4,706 bars:

| \|lead\| at close | error rate |
|---|---|
| 0–2 bps | 10.73% |
| 2–5 bps | 0.48% |
| **5+ bps** | **0.00%** |

Above 5 bps the feed is perfect. There is no strike-offset or Chainlink
mismatch worth chasing at the leads we trade. **Every flip is genuine price
movement between our sale and the close.**

### 4b. Therefore the exposure is *time*, and time is cheap to cut

Flip rate by placement moment, 10 bps floor:

| place at | flip% | EV/share | EV/placement ($50, 35% fill) |
|---|---|---|---|
| 45 s | 0.53% | +0.0047 | +$0.082 |
| 30 s | 0.31% | +0.0069 | +$0.120 |
| 15 s | 0.18% | +0.0082 | +$0.143 |
| 12 s | 0.18% | +0.0082 | +$0.143 |
| 10 s | 0.12% | +0.0088 | +$0.154 |
| 5 s | **0.06%** | +0.0094 | **+$0.165** |

~~Selling later is nearly free: fills are *instant matches against a standing
bid* (every live fill returned `matched=True` at placement), so resting longer
buys nothing — only exposure.~~ **RETRACTED 2026-08-05 — see below.** Deployed
2026-08-04 01:20 on this reasoning, window narrowed 15–45 s → ≤12 s; it
produced a full day of zero fills and was reverted.

**What the claim got wrong** (264 placements, 20 h live, scored by matching
`PF_SALV_PLACE matched=` to the bar's `PF_SETTLE salv_fill`):

| at placement | n | filled |
|---|---|---|
| `matched=True` (instant cross) | 57 | **100%** |
| `matched=False` (rested) | 207 | **10%** |

**27% of all fills came from RESTING orders.** The original claim was an
artefact of only ever inspecting fills that had already matched instantly —
survivorship in the log-reading, not in the market. Resting time is not free
optionality to be traded away for a lower flip rate; it is a quarter of the
revenue. Combined with §5 item 1 (late placements find `best_bid = 0`), the
15–45 s window earns its keep twice: it catches the instant crosses *and* gives
the other 27% time to fill.

The residual question is whether the 1¢ bid population is thinner in the last
10 seconds than at t−40 s. Live data cannot answer it yet (fills observed at
tl 8.8 s, 14.7 s, 15.3 s, 30 s, 44 s — all bands). If the late window starves,
step back to ≤20 s, which still measures 0.12%.

## 5. Ranked improvements

**1. Later placement window — TRIED AND REVERTED. It optimised the flip rate
into zero fills.** The calibration was right that flips fall from 0.53% at
t−45 s to 0.06% at t−5 s. What it could not see is the other side of the
coupling: instrumenting the book at placement time (`best_bid`, `bid_sz` in
PF_SALV_PLACE) shows placements inside 20 s read **best_bid = 0.0** — the
corpse has no bid at any price. ~60 placements and a full trading day
produced **zero** fills. Reverting to 15–45 s produced a `matched=True` fill
on the very first placement, at t−39.6 s against a 1¢ bid.

The lesson generalises: **flip rate and fill rate are the same variable
viewed from two sides.** Anything that makes our sale safer makes the corpse
less attractive to the only people who would buy it. The window is not a free
parameter to optimise — it is the price of having a counterparty.

**2. More markets, not more size.** EV per placement is fixed by `fill_rate ×
(0.01 − p)`; total profit scales with placement count. Gated minting made
capital nearly free — a pair is held ~110 s of each 300 s bar, so $50/bar
occupies ~$110 across six coins. The same balance supports 15–20 markets.
Candidates in order: **15m and 1h series** (3–12× better gas per placement,
and their losers are deader at the bell), then any additional coins Polymarket
lists. **The binding constraint is no longer capital — it is the shared
signing wallet's in-flight transaction cap.** Adding markets means adding a
second signer, not more balance.

**3. Per-coin calibration.** Flip rates differ materially by coin at the same
z (xrp 0.00% at z≥2.4 over 484 samples; btc 0.92%). Today all six run
identical gates. Per-coin floors would let the clean coins trade more and the
dirty ones less. Cheap to compute from existing data; needs a config schema
change.

**4. Gasless minting.** ~$0.01/mint, ~$11–16/day at six coins, which is a
material share of gross at these margins. Blocked: Polymarket's relayer
`/submit` requires a partner API key (probed — our L1 *and* L2 CLOB
credentials both return 401). `engine/relayer.py` already implements the path;
it needs credentials from Polymarket, not code. **Worth asking them for.**

**5. Session gating — probably unnecessary now.** All three post-filter
reversals landed 15:30–19:00 Kyiv, which suggested halting that window. But
the hour-sliced calibration shows the US session is *not* dangerous per se: at
a 10 bps floor its flip rate is **0.34%, lower than the quiet window's 0.55%**.
It is dangerous at *marginal* leads (6–9 bps: 2.54%). The floor already
handles it; a time halt would forfeit the session that supplies 57–82% fills.
Re-examine only if reversals recur at 10 bps.

## 6. Tested and rejected

- **Post-sale stop-loss buyback** (buy the sold leg back when the lead decays,
  capping the loss at a few cents). Measured on the calibration set: at a 2 bps
  trigger it saves ~$2.76 per 100 placements at $50; at 1 bps and 3 bps
  triggers it *loses* money. The reason is the buyback price — by the time the
  lead has decayed, the sold token has repriced to a median 17–60¢, so the
  "cheap" buyback is not cheap. n=9 flips; not robust. **Shelved, not dead** —
  revisit with a faster trigger that fires on the Binance tick rather than the
  decayed lead, where the book may not have repriced yet.
- **Selling at 2¢ instead of 1¢.** Forfeits the 84% of fills that execute at
  exactly 1¢. The current marketable limit already captures better bids.
- **Higher floors (15–19 bps).** Better flip rates on paper (0.28–0.30%) but
  live fill rate at 15+ bps is 0 of 3 — the corpse is too obviously dead to
  attract a bid. The safety is illusory because nothing trades.
- **Selling the kept winner on decay** (exit at ~50¢). EV-neutral: holding is
  −$42.59, exiting is −$49 at a 43.6% post-decay flip rate. Only viable with
  an exit above ~55–60¢, i.e. reacting within seconds of the first decay tick.

## 6b. ⛔ THE FINDING THAT ENDS THE PROGRAM (2026-08-06)

**Every backtest in this document measured a population we cannot trade.**

Splitting gate-passing bars (|lead|>=8bps) by whether a counterparty existed
-- i.e. whether a 1c bid was resting on the corpse at placement time:

| at t-35s | n | flips | rate |
|---|---|---|---|
| **FILLABLE** (a bid exists) | 620 | 8 | **1.29%** |
| no bid -> no trade possible | 1420 | 3 | 0.21% |

**6.1x.** The same split at t-45s gives 3.7x, at t-30s 7.3x. Bars are safe
*because* nobody will take the other side; the moment someone will, the flip
rate crosses the 1% break-even.

This reconciles every open discrepancy at once:

- Model said 0.54% (all gate-passing bars). Live ran 2.3% (3 flips / ~130
  fills). Fillable-conditioned backtest says 1.29%. Live and fillable agree;
  the 0.54% was never achievable.
- The zero-fill day (§5 item 1, §7b) was the same effect from the other side:
  t-20s bars show 0 flips in 239 samples *and* 0 fills. We found the safe
  population and discovered it is safe because it is untradeable.
- The session-floor rationale (§5 item 5) and the hour slices in §4b are
  computed on the unfillable-inclusive population and are therefore void.

EV at 1.29% = `0.01 - 0.0129` = **-$0.0029/share = -$0.29 per $100 bar**,
about -$26/day at our fill rate. Realised: +$35.64 peak (05 Aug 15:59 Kyiv)
-> -$220 vs run start after three reversals (sol -$99, bnb -$49.50, xrp -$92).

**Limits, stated honestly:** 8/620 gives a 95% CI of 0.40-2.18%, which still
touches profitability. Pooling with live (~11/750 = 1.47%) gives ~0.6-2.3%.
Not proof beyond doubt -- but the mechanism is principled, not data-mined,
and two independent measurements land on the same side.

**What does NOT fix it:** floors, windows, z-tiers, volatility filters,
session halts, per-coin calibration. All of them select on the lead; none
changes who is willing to be our counterparty. Rejected hypotheses tested
2026-08-06: flips do NOT cluster by session hour (pooled 0.54%, the three
live reversal hours measured 1.37%/0.00%/0.00% historically); late-bar
volatility DOES drive flips (0% calm -> 9.76% at >2x spike, monotone over
2,027 bars) but is NOT predictable from pre-sale volatility (flat across
buckets; skipping high-ratio bars leaves the flip rate at 0.55%).

## 7. Honest position

At $50 × six coins with the current gates, modelled expectation is roughly
**+$25–30/day** — provided the 10 bps floor holds the flip rate near its
calibrated 0.46%. Monday ran at 8 bps and produced **5.8% flips per fill**,
which at $50 would be ≈ −$250/day. That gap between model and live is the
single biggest open risk, and it is why size went to $50 rather than $100.

The strategy is real but small. Its edge is a 1¢ rounding artefact, harvested a
cent at a time, against a tail that is 99× the size of each win. It survives
only while `p < 1%`, and every design decision — floors, windows, gates — is in
service of that one inequality.

## 7b. The zero-fill day (2026-08-04) — how it was diagnosed

Worth recording because the false leads were expensive:

1. Orders posted `status: live`, then read back `status=INVALID, matched=0`.
   INVALID looks like an order-validity failure and sent me hunting for
   balance/allowance/token-id bugs.
2. A controlled test sell disproved all of them: the CLOB saw our full 100
   shares and max allowances on all three exchange contracts, and the token id
   matched the market's canonical pair.
3. The same test printed `book bids: []`. Adding `best_bid` to the placement
   event confirmed it live. INVALID is simply the terminal state of an order
   that never matched before its market closed — a symptom, not a cause.

**Diagnostic to keep:** log the counterparty side of the book at decision
time. Without it, "no fills" is indistinguishable from "broken orders", and
the two lead to opposite fixes.

## 8. Next measurements, in order

1. **Fill rate in the ≤12 s window** (does the late window starve?) — one
   session answers it.
2. **Live flip rate at 10 bps** vs the 0.46% model — the number that decides
   whether size goes to $100 or back to $20.
3. **Per-coin flip/fill table** from live data once ~500 placements exist.
4. **15m/1h series pilot** — same code, `BAR_SECONDS` differs; the gas
   arithmetic alone justifies it.

---

## 7. POST-TWAP REVALIDATION + RESTART (2026-08-13, appended per docs discipline)

Everything above predates the 2026-08-07 TWAP settlement switch. Revalidated
on 7 days of post-TWAP mrec data (2,018 btc 5m bars) before restarting:

**Demand side ALIVE (the decisive check):** corpse-BUY flow on the losing
token at ≤5¢ in the salvage window t−45..−15s = **375,328 sh/day**, present
in 83% of bars; 2.88M shares printed at exactly 1¢ over the week. Revenue
ceiling ~$4.5k/day/coin — our droplet-share thesis intact. (Caveat: unified
book print-mirroring could overstate this ≤2×; ample either way.)

**Risk side IMPROVED — flip calibration by sale moment × |lead| band:**
t−45s: 6-8bps 1.73% (3/173), **≥8bps 0/271 (0.00%)**; t−30/−20/−15s: 0
flips in all 1,373 samples. TWAP averaging makes leads stickier than the
pre-switch point-close (was 0.53% @45s/10bps). The 8bps floor stands
validated; 95% upper bound at ≥8bps pooled ≈ 0.3%.

**Corrected economics at small scale** (the honest math — an earlier
+$10-20/day estimate wrongly used the MINT rate as the placement rate):
leads ≥8bps ≈ 13% of bars → ~35-40 placements/day btc; quiet-session fills
12-17%, US session 57-82%. btc-only at $35 bars ≈ breakeven with the US
session halted, **+$2-5/day with it enabled**. Scaling is coins, not size
(6 coins ≈ $420 in flight — future capital decision).

**RESTART (user-approved config, live 2026-08-13 ~19:47 Kyiv, helm rev 35+):**
btc-only, pmMintUsd **35**, pmMintGateBps **6** (was 4 — cuts ~10× gas waste
of minting bars that never reach the 8bps sale gate), pmLeadFloorBps 8,
session floor 10 (12:30-16:00 UTC) KEPT, **pmHaltWindowUtc=off** (user
removed the 2026-08-05 Kyiv-window halt — calibration shows 0/271 flips
≥8bps incl. that session; NOTE: helm `--set-string ...=""` does NOT override
a `default` in the template — use the literal `off`, the parser disables on
any dash-less string), liveMaxDailyLossUsd 40, liveMaxOrderUsd 5. Fleet
purged same evening per user: ALL other trader bots removed (9 twapedge +
4 poolfarm releases); running = mintsalvage + btc-sweeper (redemptions) +
10 recorders. Signer gas 0x7BbD..3AD3: **172.03 POL** (~months at ~$0.01/
mint; track burn in scratchpad gas_track.txt). Monitoring: persistent
problem-monitor (fills/settles/reversals/halts/gas+RPC errors) + 30-min
quiet cron (reports only on trades/errors/gas anomalies). Known-benign:
one "Could not create api key" 400 at startup (client derives existing key).

---

## 8. POST-TWAP LIVE RESULT: STOPPED 2026-08-14 ~11:30 Kyiv — the edge is dead

16h live (btc, $35 bars, gate 6, floor 8, no halt window): 47 mints, 27
salvage placements, **0 fills**, all settles $0 (breakeven by construction),
~7.7 POL gas (~$1.1). p(0/27 | doc-era fill rates) ≈ 1-4%.

**Root cause (measured, 7d recorder data): the TWAP switch killed the fill
path.** Our 1¢ loser-ask ≡ joining the 0.99 winner-bid queue. Post-TWAP the
outcome is knowable minutes early, so the 0.99-vacuum fleets wall the level
long before our t−45s placement: standing queue at t−45 on decided bars =
**median 942sh, p75 4,566sh** (n=503); the ~1,200sh/bar of 1¢ executions is
consumed by the wall — a late 35sh ask never reaches flow. Pre-TWAP fills
existed BECAUSE ambiguity kept that queue thin until the final seconds.

**Early placement doesn't rescue it:** flip rates at ≥8bps are 4.76% @t−90
and 2.41% @t−120 (one flip = −$35 vs +$0.35 max win → ruinous). Only ≥15bps
is flip-free early (0/79 pooled t−90/−120) but that's ~4 bars/day → ≤$1.5/day
gross − $1-2/day gas ≈ breakeven with tail risk. Not worth code or capital.

**Revival conditions (all required):** (a) a mechanism to be FRONT of the
0.99 queue (earlier + bigger + faster than the vacuum fleets — capital and
infra we don't have), or (b) a return of late-flip ambiguity (venue rule
change), or (c) gasless minting via partner relayer key + multi-coin scale
making the ≥15bps-early variant's ~$1/day/coin × N worth it. Otherwise:
CLOSED. The Aug-2-5 profitable era was a pre-TWAP artifact.
