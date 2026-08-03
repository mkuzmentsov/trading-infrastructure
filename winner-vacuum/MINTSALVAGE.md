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

Selling later is nearly free: fills are *instant matches against a standing
bid* (every live fill returned `matched=True` at placement), so resting longer
buys nothing — only exposure. **Deployed 2026-08-04 01:20: window narrowed
from 15–45 s to ≤12 s.**

The residual question is whether the 1¢ bid population is thinner in the last
10 seconds than at t−40 s. Live data cannot answer it yet (fills observed at
tl 8.8 s, 14.7 s, 15.3 s, 30 s, 44 s — all bands). If the late window starves,
step back to ≤20 s, which still measures 0.12%.

## 5. Ranked improvements

**1. Later placement window — DONE (≤12 s).** ~3× lower flip rate, ~2× EV.
Zero implementation risk. Verify fill rate holds over the next session.

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

## 8. Next measurements, in order

1. **Fill rate in the ≤12 s window** (does the late window starve?) — one
   session answers it.
2. **Live flip rate at 10 bps** vs the 0.46% model — the number that decides
   whether size goes to $100 or back to $20.
3. **Per-coin flip/fill table** from live data once ~500 placements exist.
4. **15m/1h series pilot** — same code, `BAR_SECONDS` differs; the gas
   arithmetic alone justifies it.
