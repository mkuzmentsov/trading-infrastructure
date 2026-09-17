# HYPE perp on Hyperliquid — venue mechanics & cost layer

Owner: venue-mechanics agent. Date: 2026-09-17. **Read-only research. No orders placed, no funds moved, nothing changed.**

Sources: live `api.hyperliquid.xyz/info` (read-only), our own fill receipts (2,666 historical fills across
master+sub), 101 h of native HYPE tick tape at `every-tick-single/data/pq-venue/hl/`, and the official docs
pulled as raw Markdown (every gitbook page serves `.md`; index at `.../llms.txt`).

Convention: every cost is in **bps of notional**, one-way unless it says "RT" (round trip = entry + exit).

---

## 0. The headline, corrected

The framing that launched this round was: *spread 0.12 bps, taker fee 4.5 bps, so the fee is 37× the spread
and only the maker lane can survive.* Both halves need fixing.

**The maker lane is not free.** At our tier the maker fee is **1.44 bps per side, 2.88 bps RT** — that is
**24× the median spread**. Quoting both sides to capture the spread earns 0.12 bps RT and costs 2.88 bps RT:
**−2.76 bps per round trip before any adverse selection.** Pure spread-capture market making on HYPE is dead
by a factor of 24, and no reachable fee tier fixes it (§2).

**But the spread is the wrong comparator.** The spread is not the opportunity — volatility is. From 93 h of
second-sampled mid:

| horizon | mean abs. move | P(move > 2.88 bps) |
|---|---|---|
| 1 s | 0.57 bps | 3.9% |
| 10 s | 2.96 bps | 36.4% |
| 60 s | **8.17 bps** | 73.1% |
| 300 s | 18.52 bps | 88.6% |

Realized vol **9.54 bps/min, 69% annualized**. So:

> **The fee is 37× the spread but only 0.35× the average 1-minute move.**
> Maker RT (2.88 bps) = a **5-second** 1-sigma move. Taker RT (8.64 bps) = a **49-second** 1-sigma move.

This is the real inversion of the Polymarket result. There, the fee was the same order of magnitude as the
entire mispricing, which is why every cell closed. Here a minute-horizon strategy has ~8 bps of move to play
for against a 2.88 bps maker hurdle. **The maker lane needs to capture ~35% of a 1-minute move; the taker
lane needs ~106% of one.** Taker is a very high bar. Maker is a normal, hard, but live bar.

---

## 1. The exact fee stack we would face (verified on receipts, not docs)

### 1.1 Base schedule — live from `userFees`

Perp: `cross` (taker) **0.045%**, `add` (maker) **0.015%**. Spot: 0.07% / 0.04%.
Tier is on **14-day rolling weighted volume**, assessed at UTC end-of-day, where
`weighted = perp_volume + 2 × spot_volume`, one tier across perps, HIP-3 perps and spot.

### 1.2 What we actually pay — three exact rates found in our own fill history

Per-fill `fee / (px·sz)` on our 2,666 receipts collapses onto exactly three values for perp takers:

| rate | = | where seen |
|---|---|---|
| **4.500 bps** | base, no discount | master 2025-09→2025-12 (n=42); sub 2026-06/07 (n=44) |
| **4.320 bps** | 4.5 × 0.96 → 4% referral | master 2026-02-18→26 (n=216) |
| **4.275 bps** | 4.5 × 0.95 → 5% staking (Wood) | sub 2026-03/04 (n=1,349) |

Maker receipts: **exactly 1.5000 bps** on our master pre-referral; **exactly 1.4400 bps** (= 1.5 × 0.96) on
four independent referred accounts, n=247 maker fills. So:

> ⭐ **The 4% referral discount applies to the maker fee as well as the taker fee.** Verified on 247 maker
> fills at 1.4400 bps. (It does *not* apply to a *negative* maker rate — the docs' own `feeRates()` reference
> implementation skips the referral multiplier on the rebate branch. Academic for us; see §2.3.)

### 1.3 ⭐ We are leaving 4% on the table right now — the free, zero-capital lever

```
master 0xD17E2499…  activeReferralDiscount = 0.04   (referred by code CCXT1, i.e. ccxt's default)
sub    0x65ce540d…  activeReferralDiscount = 0.00
```

The referral discount is **address-scoped and explicitly excluded from sub-accounts and vaults** (docs:
"Referral discounts do not apply to vaults or sub-accounts because those are treated as independent accounts
in the clearinghouse"). Our sub's own 2026-06/07 fills confirm it empirically: **4.500 bps, full base.**

**The MCP trades the sub.** Trading the same strategy from the master instead is worth **4% of all fees, both
sides, forever** (to $25M of volume — we are at $205k):

| | sub (today) | master |
|---|---|---|
| taker | 4.500 | **4.320** |
| maker | 1.500 | **1.440** |
| maker RT | 3.000 | **2.880** |
| taker RT | 9.000 | **8.640** |

**0.12 bps per RT of pure, free saving — coincidentally equal to the entire median spread.** This is a config
decision for the user, not a deploy; note it also gives up whatever sub-account risk isolation we wanted.
(Fee *tiers* are shared master↔sub; only the referral discount is not.)

### 1.4 Composition order

`effective = base_tier_rate × (1 − staking_discount) × (1 − referral_discount)`, multiplicative, staking first.
Confirmed two ways: the docs' reference implementation, and live `userFees` — an account with
`activeStakingDiscount = 0.3` reports `userCrossRate 0.000315` (= 0.00045 × 0.7) and `userAddRate 0.000105`
(= 0.00015 × 0.7). **`userCrossRate`/`userAddRate` already contain the staking discount but NOT the referral
discount** — referral is applied at fill time. Do not double-count.

---

## 2. Is a better tier reachable on a small bankroll?

Bankroll available: ~$467 (would have to be moved off Polymarket). HL account today: master $0.0006, sub $0.0009.

### 2.1 The volume ladder and what each rung is worth

| tier | 14d wtd vol | taker | maker | maker RT (w/ 4% ref) | $/day needed | = % of HYPE's $530M/day |
|---|---|---|---|---|---|---|
| 0 | — | 4.5 | 1.5 | **2.880** | — | — |
| 1 | >$5M | 4.0 | 1.2 | 2.304 | $357k | 0.067% |
| 2 | >$25M | 3.5 | 0.8 | 1.536 | $1.79M | 0.34% |
| 3 | >$100M | 3.0 | 0.4 | 0.768 | $7.14M | 1.35% |
| 4 | >$500M | 2.8 | **0.0** | **0.000** | $35.7M | 6.7% |
| 5 | >$2B | 2.6 | 0.0 | 0.000 | $143M | 27% |
| 6 | >$7B | 2.4 | 0.0 | 0.000 | $500M | 94% |

**Tier 4 is where the maker lane becomes genuinely free**, and it needs 6.7% of all HYPE volume — on a $467
bankroll that is ~71,000× daily turnover. **Closed.**

**Tier 1 is the only one worth discussing.** $357k/day of volume. At a sane 2× leverage ($1,000 notional) that
is 178 round trips/day, one every 8 minutes, sustained, 24/7 — and it is only 0.067% of HYPE's flow, so the
book can absorb it. It buys **0.576 bps off the maker RT** (2.880 → 2.304, a 20% cut). Verdict: *reachable in
principle by a genuinely high-frequency maker, irrelevant to anything slower.* It is a consequence of running
the strategy, never a reason to run it — do not trade for volume.

**Do not buy tier with spot volume.** Spot counts double toward the tier but costs 4 bps maker vs 1.5 bps
perp: $1 of tier credit costs 2.0 bps via spot maker vs 1.5 bps via perp maker. Perp is strictly cheaper per
unit of tier credit. Closed.

### 2.2 ⭐ The staking discount — the lever capital pulls, and why it still fails at our size

Verified thresholds. `bpsOfMaxSupply` in the API times a max supply of exactly 1e9 HYPE (implied 1.00006e9
from three live accounts — rounding only) gives:

| tier | HYPE staked | value @ $83.4 | discount (taker **and** maker) |
|---|---|---|---|
| Wood | >10 | $834 | 5% |
| Bronze | >100 | $8,340 | 10% |
| Silver | >1,000 | $83,400 | 15% |
| Gold | >10,000 | $834,000 | 20% |
| Platinum | >100,000 | $8.34M | 30% |
| Diamond | >500,000 | $41.7M | 40% |

Unlike the volume ladder this is buyable with capital, and unlike the referral it scales the **maker** fee
too. But at our size the first rung costs **$834 — 1.8× the entire bankroll — to save 5% of 2.88 bps =
0.144 bps per maker RT.** Naked, that is a 1.8×-bankroll long HYPE position taken on to shave a seventh of a
bp; a 10% HYPE drawdown costs $83, i.e. 18% of the bankroll. **Anti-economic. Closed at this bankroll.**

The structure that makes it *not* absurd at a larger size, flagged for the capital agent:

> **Stake 10 HYPE + short 10 HYPE perp.** Delta-flat. Earns HYPE staking rewards, **receives HYPE perp
> funding (+13.7% APR, §3)**, and unlocks the 5% fee discount. Capital ≈ $834 spot + ~$278 margin at 3× ≈
> **$1,100**, i.e. 2.4× what we have. Risks: funding flipping negative (7.2% of hours, 1 day in 22 — §3),
> spot/perp basis, liquidation of the short, and **7-day unbonding** on the staked leg, so the hedge cannot be
> unwound fast. This is the same trade shape as the existing funding-carry book. **Not reachable today; it is
> the one fee lever that capital rather than volume unlocks, and at +13.7% funding it is self-financing.**

### 2.3 Maker rebates — where maker goes negative

`feeSchedule.tiers.mm`: maker fraction >0.5% → −0.1 bps, >1.5% → −0.2 bps, >3.0% → −0.3 bps.
The denominator is undocumented; `dailyUserVlm` returns `{userCross, userAdd, exchange}` and the live
`exchange` figure is **$94.9B over 15 days ≈ $6.33B/day**. So tier 1 needs roughly **$31.6M/day of our own
maker volume**. That is 6% of HYPE's entire daily volume, or ~68,000× our bankroll per day.

> **We never get paid to make. The best maker rate we can reach is +1.44 bps (tier 0 with referral), and the
> best reachable-in-principle is +1.152 bps (tier 1 with referral). Negative maker is closed by ~4 orders of
> magnitude.**

### 2.4 Referral, the other direction

We could create our own code (needs $10k of volume) and earn 10% of referred users' fees. **Self-referral is
structurally pointless**: the master's referral relationship is already permanently bound to `CCXT1`, and
sub-accounts and vaults are explicitly excluded from *receiving* a discount — so there is no address we
control that could both pay us 10% and keep the 4%. Not a cost lever. **Closed.**

### 2.5 Builder codes — a cost we do not pay and must not start paying

`builder` is an optional field on the order action charging **`f` tenths of a bp on top of the exchange fee**,
capped at 0.1% on perps, paid by us to the builder. It requires an explicit `approveBuilderFee` action signed
by the **main wallet, not an API wallet**.

Verified we are clean: `maxBuilderFee` for our master against an unapproved builder returns **0**, and
`builderFee` is `None` on **all 2,666** of our historical fills. **Builder codes are strictly additive cost.
The only correct action is to never approve one** — and to check that any SDK/client we adopt does not
silently populate the field.

### 2.6 Everything else that touches cost

| item | cost | verified |
|---|---|---|
| Funding payments | **no fee**, purely peer-to-peer | docs |
| Liquidation | **no clearance fee** on book liquidation | docs |
| Backstop liquidation (equity < 2/3 MM) | **entire maintenance margin forfeited** | docs |
| Withdrawal | **exactly $1.00 flat** | ⭐ our own ledger, two withdrawals, `fee: "1.0"` |
| Deposit | free (min 5 USDC or it is **lost forever**) | docs + our ledger |
| Spot↔perp, sub-account, vault transfers | free | docs |
| New-account activation | 1 quote token on first inbound transfer | docs |
| Vault creation | 10,000 USDC | docs |

> ⭐ **The $1 withdrawal fee is 21 bps round trip on a $467 bankroll.** On a book this small, moving money in
> and out is one of the largest single costs on the page — larger than 70 maker round trips. Size the transfer
> once and leave it; this belongs in CAPITAL.md.

---

## 3. Funding — formula closed, and it is a live, structural signal

### 3.1 The formula, confirmed to the last digit

```
funding_hourly = avg_premium + clamp(0.0000125 − avg_premium, −0.0005, +0.0005)
```
where `avg_premium` is the premium sampled every 5 s and averaged over the hour, and
`premium = impact_price_difference / oracle_px` using a **$6,000 impact notional** for HYPE ($20,000 for
BTC/ETH only). The 0.0000125 interest component is the 0.01%/8h rate expressed hourly. Cap ±4%/hour.

Tested against 48 h of `fundingHistory`: **45/48 hours reproduce exactly** from the returned snapshot premium.
The 3 that do not are precisely the hours where the snapshot premium differs from the hour-average — inverting
the formula recovers `avg_premium` = −0.000489, −0.000493, +0.000652, each landing exactly on the clamp
boundary. **Formula confirmed; the `premium` field returned by `fundingHistory` is a snapshot, not the input.**

Settlement is at the **exact top of each UTC hour** (`1789671600007` ms against a 1789671600000 boundary).
The docs never state this; it is empirical.

### 3.2 The consequence

Funding sits **pinned at the +0.00125%/hour floor whenever the hour-average premium is inside
[−4.875, +5.125] bps** — which on HYPE is **71.4% of hours over the last 500 hours**, and 72.9% of the 101 h
tape. The floor is positive by construction, so:

> **The short side of HYPE perp earns a structural +10.95% APR simple / +11.6% compounded whenever the premium
> is in band.** Realized over 500 h: mean **+3.76 bps/day = +13.72% APR paid by longs**. Only **1 of 22 days**
> was net negative; 7.2% of individual hours were negative. Range −4.47e-5 to +1.81e-4 per hour.

Two things follow for the other agents:

1. **For a long-biased book, funding is a real cost: 3.76 bps/day = one maker RT every 18 hours, or one taker
   RT every 55 hours.** Negligible at minute horizons (0.063 bps/min); decisive at daily ones. Any model that
   holds overnight must carry it.
2. **Funding is a directional prior with a known sign**, and it is the only HL mechanism here that pays for
   holding rather than charging for it. Hand this to the models agent as a feature and to the capital agent
   as the financing leg of §2.2.

Note: funding notional uses the **oracle price, not the mark price** — `position_size × oracle_px × rate`.

### 3.3 ⭐ HYPE's oracle has no external sources — and this matters

> "Perps on assets which have primary spot liquidity on Hyperliquid (e.g. HYPE) do not include external
> sources in the oracle until sufficient liquidity is met."

The normal HL oracle is a stake-weighted median of validator submissions, each a weighted median of Binance
(3), OKX (2), Bybit (2), Kraken, Kucoin, Gate, MEXC, HL spot (1 each), republished every 3 s. **For HYPE that
entire list collapses to Hyperliquid spot alone.** Combined with the fact that HYPE has no Binance listing:

> **HYPE perp funding, margining and liquidation are all driven by a price that is computed from the HYPE
> order book on the same venue. There is no external anchor.** There is no cross-venue reference to arbitrage
> against, and equally no external price that can drag the oracle. The only "second opinion" available is HL
> **spot** HYPE, which is a genuinely independent book from the perp — that is the closest thing to a lead
> signal this coin has, and it is the one avenue I would hand to the data agent.

Mark price (used for margin/liquidation/TP-SL, distinct from oracle) = median of (oracle + 150 s EMA of
HL mid − oracle), (median of best bid/ask/last on HL), and (a CEX perp median that for HYPE is largely empty).

---

## 4. Execution mechanics that change the economics

### 4.1 ⭐ The venue structurally protects makers — the exact opposite of Polymarket

Within each consensus batch, HL sorts actions:
1. actions that send no GTC/IOC order (**ALO / post-only**),
2. **cancels**,
3. actions sending at least one GTC or IOC.

> "cancels and ALO orders sent at time `t` will almost always execute before IOC and GTC orders sent at time
> `t`. **This prioritization spans several blocks.**"

**A taker can never beat a same-instant cancel.** On Polymarket we established the reverse — "a maker can never
sweep", and adverse selection was unavoidable. Here the venue gives the maker a structural last look. This does
*not* eliminate adverse selection (a taker who saw the move 200 ms earlier still runs us over), but it removes
the same-tick race, and it is the single biggest reason the maker lane deserves the microstructure agent's time.

### 4.2 Block cadence — confirmed from our own tape

Docs imply ~70 ms blocks ("each 70ms unix time bucket"). Our tape confirms it independently: the modal gap
between distinct bbo timestamps is **66–68 ms**, with clean harmonics at **133–135 ms** (2 blocks) and
**199–203 ms** (3 blocks), across 1,910,728 updates. Trades cluster the same way (up to 741 trades and 110
distinct tx hashes on a single timestamp). Median bbo inter-update gap 121 ms.

Documented latency: median 0.2 s end-to-end, p99 0.9 s for a co-located client.

### 4.3 Order types actually available

Only **three TIFs are documented: `Alo`, `Ioc`, `Gtc`.** ⚠️ `FrontendMarket` and `LiquidationMarket` appear in
node/fill data and some SDKs but have **zero occurrences anywhere in the docs** — treat as unsupported.
`deferExec` likewise does not exist on this venue (zero hits site-wide); that was a Polymarket artefact.

Also available and worth knowing: `trigger` orders (TP/SL, fired off **mark price**, 10% slippage tolerance);
`modify`/`batchModify` with an `always_place` flag (when false, the replacement is forced to ALO —
**the correct primitive for a requoting maker**); `cancel` with a `fast` flag (currently inert, will prioritise
in the mempool in a future upgrade; note `f` must be *omitted* when false or the action hash is rejected);
`scheduleCancel`, a dead-man's switch (≥5 s out, **max 10 triggers per UTC day**); `expiresAfter` (stale ones
burn **5×** rate limit); 128-bit `cloid`. **"Scale" orders are frontend sugar — there is no scale action.**

**TWAP orders** exist as a first-class action (`twapOrder`): 5 min to 7 days, $100 minimum, ≥30 s intervals,
±20% randomisation, 3% max suborder slippage, catch-up capped at 3× normal suborder size. ⚠️ The docs never
state whether suborders pay taker or maker, but they carry a slippage cap and "like normal market orders" do
not fill during post-only periods — **assume taker (4.32 bps) and do not model TWAP as a fee reduction.**

### 4.4 Self-trade prevention — mandatory, and a sub-account trap

> "Trades between the same address cancel the resting order instead of causing a fill. No fees are deducted."

Expire-maker, **address-scoped, always on, not configurable**. ⚠️ The scoping is the trap: **sub-accounts are
separate addresses, so a master and its sub will happily trade against each other and pay full fees on both
sides.** The docs do not warn about this. If we ever run two strategies on master+sub, they must not quote the
same book on opposite sides.

### 4.5 ⭐ The rate limit is a volume identity — and it binds a small maker

```
nRequestsCap = 10,000 + floor(cumVlm)
```
Verified exactly on our master: `cumVlm 205001.52` → `nRequestsCap 215001`. One L1 action per USDC ever
traded, plus a 10,000 starting buffer. Cancels get a separate, larger budget of `min(limit + 100000,
limit × 2)`. Address-scoped, **sub-accounts counted separately**, info requests exempt. When exhausted: one
action per 10 seconds. Batches count as `n` actions for this limit (but 1 for the IP limit).

The binding form for a maker: each quote cycle is 1 place + 1 cancel = **2 actions**, and earns `clip × fill_rate`
of budget.

> ⭐ **A requoting maker must satisfy `clip_size × fill_rate > $2 per order placed`, or it runs out of actions
> and gets throttled to one action per 10 seconds.** At the venue's **$10 minimum order value** that demands a
> **≥20% fill rate**. At a $50 clip, ≥4%. At a $200 clip, ≥1%. **Small clips plus fast requoting is
> rate-limit death on a fresh account** — and our master starts with only 215,001 actions banked, ~10 hours at
> 5 actions/second.

Other ceilings: IP 1,200 weight/min (we hit 429 once during this research); 1,000 open orders (+1 per $5M
volume, cap 5,000); WS 10 connections / 1,000 subscriptions / 2,000 msgs per minute.

### 4.6 Priority fees — a paid queue-position market, and it is not for us

HL runs two things the `/trading/market-making` page still (stalely) denies exist:
- **Write priority** via `grouping: {"p": N}`, rate `N/1e8`, paid from the **undelegated staking balance**,
  converted to HYPE and **burned**. For IOC it buys latency (~45 ms per bp, linear 0–8 bps). ⭐ For **ALO it
  buys queue position**: orders placed within a trailing 400 ms window are sorted by priority rate, so you can
  bid your way toward the front of a price level — but once an order has rested 400 ms its slot is locked and
  cannot be jumped. **ALO priority is charged whether or not the order fills.**
- **Gossip (read) priority**: two Dutch auctions every 3 minutes, floor 0.1 HYPE. Live right now: one slot at
  7.38 HYPE and falling, the other **unsold at the 0.1 HYPE floor**. Worth ~25 ms of read latency per slot.

Costing the cheap one: holding the floor-priced slot continuously is 0.1 HYPE × 480 auctions/day = **48
HYPE/day ≈ $4,000/day**. Against a $467 bankroll. **Closed with a number.** Write priority is only sanely
priced in bps-of-notional terms and is a pure add to the 2.88 bps hurdle — **closed for us, but it is proof
that someone is paying for queue position on this venue, which is a fact the microstructure agent should
fold into any fill-rate assumption.**

---

## 5. HLP, vaults, liquidations

### 5.1 HLP is our counterparty, and it is large and flat

HLP is a protocol vault that "provides liquidity through **multiple market making strategies, performs
liquidations, supplies USDC in Earn, and accrues a portion of trading fees**." Live state:

- Master vault $48.2M equity, **0 positions** — it is a holding account.
- Strategy children: `0x010461c1…` $3.13M / **177 positions**, and `0x31ca8395…` $3.03M / **177 positions**.
  Both carry HYPE: −549.32 and +512.34. **Family net HYPE = −36.98 HYPE (−$3,080) on $87.4M of equity.**
- Remaining children ($30M, $1M ×3) sit idle.

> **HLP quotes HYPE and runs near-perfectly delta-flat across 177 assets on $87M.** It is the maker we would
> be competing with for queue position, it takes a share of the exchange fee we pay, and it pays no fee
> itself. Any fill-rate model that assumes we can hold the touch has to beat this. Current APR 5.1%,
> all-time PnL $138M, 4-day deposit lock-up.

Depositing into HLP is a separate proposition, not a trading edge: **5.1% APR, no profit share** (protocol
vaults, unlike user vaults, charge **zero** — the widely repeated "HLP takes 10%" is wrong; the 10% leader
profit share and 1-day lock belong to *user* vaults, which additionally cost **10,000 USDC to create** and
are now labelled "legacy"). At $467 that is $24/yr. Mentioned only so the capital agent can price the
alternative to trading; it is not in our scope.

### 5.2 Liquidation — no fee, no auction, one cliff

- **Maintenance margin = half the initial margin at max leverage.** HYPE's margin table (id 52) is 10× up to
  $20M notional, 5× above. **MM = 5% for us.** Effective max leverage 10×, but see §5.3.
- Below MM: positions are **market-ordered into the book** — "this allows all users to compete for the
  liquidation flow." No fee, remaining collateral returned.
- Below **2/3 of MM**: **backstop liquidation** into HLP, and **the maintenance margin is not returned**.
  That is the real liquidation cost: **a 5% of notional loss, on top of the loss that got you there.**
- **No liquidation auction.** Partial liquidation (20%) only above $100k position size, with a 30 s cooldown —
  **irrelevant at our size; every one of our liquidations would be a full-position market order.**
- `liq_price = price − side × margin_available / position_size / (1 − l × side)`, `l = 1/MAINT_LEVERAGE`.
- Withdrawal gate: `transfer_margin_required = max(initial_margin, 0.10 × total_position_value)` — you can
  never pull equity below 10% of notional.

> **Liquidations are a tradeable flow event on this venue** — they arrive as market orders into the book, not
> as an auction, and anyone can be the counterparty. That is a genuine HL-specific mechanism with no
> Polymarket analogue. I have **not** established that it is economically live for us; it needs the
> microstructure agent to measure how much of HYPE's flow is liquidation-driven and whether the resulting
> impulse exceeds 2.88 bps. Flagging, not claiming.

---

## 6. Contract spec, HYPE

| | |
|---|---|
| asset index | **159** (validator-operated, main dex — standard fees, not HIP-3) |
| szDecimals | 2 → lot **0.01 HYPE** (≈$0.83) |
| tick | **5 significant figures**, capped at `6 − szDecimals = 4` decimals → **0.001 at current price** |
| min order value | **$10** |
| max leverage | 10× (5× above $20M notional); MM 5% |
| max market order | $2M; max limit order $20M |
| oracle | **HL spot only** (no external CEX) |
| funding | hourly, top of UTC hour, $6,000 impact notional |
| OI | ~21.2M HYPE ≈ **$1.77B** |
| daily volume | **$530M** = 8.4% of the exchange's $6.33B/day |
| spread | median **0.128 bps** (1 tick 67.5% of the time), mean 0.404, p90 1.04 |
| top of book | median **$3.3k bid / $3.0k ask** (a spot sample showed top-10 $69k/$28k — very asymmetric, do not assume the $121k figure) |
| trade rate | **209 trades/min**, median clip $270, mean $1,635 |

### ⭐ 6.1 The $100 tick cliff

The 5-significant-figure rule is exact: **1,255,728 of 1,255,728 trade prices in the tape have ≤5 sig figs**,
none more. HYPE is at $83.4 and the tape range is $75.15–$83.35, so the tick is 0.001 = 0.12 bps.

> **If HYPE crosses $100 the tick becomes 0.01 and the minimum spread jumps 8.3× to 1.0 bps overnight.** HYPE
> is 20% away. The maker fee does not change, so spread-capture economics improve from −2.76 bps RT to
> −1.88 bps RT — still negative, but the ratio of fee to spread falls from 24× to 2.9×. Every microstructure
> statistic measured below $100 should be re-derived above it. **This is the single largest known regime
> change sitting in front of this strategy, and it is a price level, not a market event.**

---

## 7. Verdicts — what is open, what is shut, with a number

| mechanism | verdict | number |
|---|---|---|
| Move trading from sub → master for the 4% referral | ⭐ **OPEN, free, zero capital** | −0.12 bps/RT |
| Spread-capture market making at tier 0 | ⛔ **CLOSED** | +0.12 earned vs 2.88 cost = **−2.76 bps/RT** |
| Maker lane with directional alpha | 🟡 **OPEN, hard** | hurdle 2.88 bps = 35% of a 1-min move |
| Taker lane | 🟡 **very high bar** | hurdle 8.64 bps = 106% of a 1-min move |
| Volume tier 1 ($5M/14d) | 🟡 reachable only as a by-product | saves 0.576 bps/RT; **never trade for volume** |
| Volume tier 4 (maker = 0) | ⛔ **CLOSED** | needs 6.7% of HYPE volume; ~71,000× bankroll/day |
| MM rebate (negative maker) | ⛔ **CLOSED** | needs ~$31.6M/day of our maker volume |
| Staking discount, naked | ⛔ **CLOSED at this bankroll** | $834 = 1.8× bankroll to save 0.144 bps/RT |
| Staking discount, funding-hedged | 🟡 **OPEN above ~$1,100** | self-financing at +13.7% APR funding |
| Buying tier with spot volume | ⛔ **CLOSED** | 2.0 vs 1.5 bps per $1 of tier credit |
| Self-referral | ⛔ **CLOSED** | master permanently bound to CCXT1; subs/vaults excluded |
| Builder codes | ⛔ **strictly additive** | we are at 0; keep it there |
| Gossip read-priority auction | ⛔ **CLOSED** | floor slot = 48 HYPE/day ≈ **$4,000/day** |
| ALO write-priority (queue position) | ⛔ closed for us | pure add to the 2.88 bps hurdle |
| Funding as a signal / carry | ⭐ **OPEN** | **+13.7% APR to shorts**, 71% of hours pinned at the floor |
| Liquidation flow as an event | 🟡 **unmeasured** | market orders into the book, no auction, anyone can take |
| HL spot HYPE as the only lead | 🟡 **unmeasured** | the only independent price that exists for HYPE |
| HLP deposit | not our scope | 5.1% APR, no profit share, 4-day lock |

### The two things I would put in front of the user first

1. **Trading from the sub costs 4% more than trading from the master, forever.** Free to fix, costs nothing,
   and is worth exactly one median spread per round trip. It is a configuration choice for the user to make —
   **not a deploy, and not mine to make.**
2. **The fee is 37× the spread but 0.35× the 1-minute move.** The maker lane survives that comparison and the
   taker lane essentially does not. Every downstream model should be scored against a **2.88 bps round-trip
   hurdle** (2.304 if we ever reach tier 1), and any result that needs the taker lane needs to clear 8.64 bps.

### Open questions I could not settle read-only

- **Whether the staking discount scales a *negative* maker rate.** Undocumented and unobservable without an
  MM-tier account. Academic — we cannot reach negative maker anyway.
- **The exact denominator of `makerFractionCutoff`.** Docs never define "maker fraction"; I used
  `dailyUserVlm.exchange` ($6.33B/day). The conclusion is 4 orders of magnitude clear either way.
- **Whether TWAP suborders pay maker or taker.** Never stated; assumed taker, which is the conservative side.
- **Real fill rates at the touch against HLP.** Cannot be established from a read-only tape — this is the
  microstructure agent's job, and it is the number that decides whether the maker lane is actually live.

**Nothing in this document is a recommendation to deploy. Read-only throughout: no orders, no transfers, no
configuration changed.**
