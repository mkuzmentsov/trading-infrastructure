# Polymarket venue mechanics for 5m crypto up/down — catalogue, the two windows, abuse tests, re-check list (2026-09-08, agent D)

**User mandate:** *"Check the polymarket documentation. Run a deep investigation of how we can abuse these markets. Record
everything found. Previous investigations may need to be re-checked. Also, market is still live after next bar is started.
Also, markets are live far in future."* Scope: 5m crypto up/down only. Written incrementally; sections marked ⏳ are pending.
Scripts: `winner-vacuum/tools/mrec/venue/`. Docs index: `https://docs.polymarket.com/llms.txt` (every page is also served
as `.md`). Live confirmations via `curl -A Mozilla/5.0` (bare urllib gets 403).

---

## 1. VENUE CATALOGUE (doc source → live confirmation)

### 1.1 Market lifecycle — ⭐ 5m markets exist ~24 h before they open, with a LIVE BOOK
- **Live (gamma, 2026-09-08 08:29 UTC):** the newest `btc-updown-5m-*` markets have `ws − now ≈ +23.3…23.8 h`,
  `acceptingOrders: true`, `enableOrderBook: true`, `orderPriceMinTickSize: 0.01`, `orderMinSize: 5`,
  `createdAt` = now, `eventStartTime` = ws (24 h later), `endDate` = ws+300. 8 coins × ~6 markets each are listed in the
  24 h window at any time (gamma top-500 by startDate: 42 updown-5m events, all 23.3-23.8 h ahead ⇒ **creation cadence is
  one market per coin per 5 min, exactly 24 h ahead**).
- **CLOB `/book` on a market 23.8 h before open already holds resting orders**: btc UP bids `0.01 × 126,017 sh`,
  `0.02 × 16,544`, `0.03 × 11,224`, `0.05 × 6,681`, `0.10 × 3,020` … — a full pre-open book. `tick_size 0.01`, `min_order 5`,
  `neg_risk false`.
- **The recorder already captures it:** raw `mrec` SNAP rows carry `role ∈ {post, cur, next1, next2, next3}` with `tl`
  ranges `post (−427…0)`, `cur (0…300)`, `next1 (300…600)`, `next2 (600…900)`, `next3 (900…1200)` — 10-level ladders on
  both tokens, 10 Hz. Only `cur` had been extracted to parquet (`snap2pq.py`); `venue/rolex.py` extracts `post` + `next1`.
- A bar that has just closed (T+0…T+15 s) is still `closed: false, acceptingOrders: true, active: true`, tick 0.01, with a
  live two-sided book (observed 0.67/0.68 with `outcomePrices [0.795, 0.205]`). Agent B confirmed 626/628 orders accepted at
  T+2.1 s. Resolution posts `post_secs ≈ 305 s` after close (recorder `RES` rows).
- `secondsDelay` (market-details doc): *"Delay, in seconds, before a newly placed marketable order can match."*
  Changelog 2026-08-17: **crypto taker delay 250 ms → 50 ms** (order status `delayed` → `matched|unmatched`; *"During
  delays, the order is pending and cannot be canceled."*) — this is the 50 ms the fleet already pays on every FAK.

### 1.2 Order types (docs: trading/place-orders.md, market-makers/trading)
- **GTC / GTD / FOK / FAK.** `postOnly: true` only with GTC/GTD; *"if it would match immediately against the book, it is
  rejected instead of taking."*
- **GTD:** *"GTD orders expire one minute before their stated expiration as a security threshold"*; expiry must be
  *"at least 3 minutes in the future"*; effective lifetime = `now + 60 + N`. ⇒ **minimum effective GTD life ≈ 2 min, and
  the expiry lands 60 s before the timestamp** — GTD cannot be used as a precise sub-bar "free cancel"; a GTD set to the
  bar's close expires at tl 60.
- **Batch:** `POST /orders` accepts **1-15 signed orders per call**, each independently accepted/rejected (`ok` per entry).
  Cancel: `/order`, `/orders` (**up to 3,000 IDs per batch**), `/cancel-all`.
- **Precision (tick 0.01):** price 2 dp, size 2 dp, amount 4 dp; *"round shares down"*. Tick table in docs: 0.1, 0.01,
  0.005, 0.0025, 0.001, 0.0001; *"Always read the active value from the market."* **The docs never state the rule that
  moves a market between ticks** — see §1.3.
- `orderMinSize` (=5) is documented as *"Minimum order size in USDC"* but the CLOB `/book` reports `min_order_size 5`
  in shares; agent B measured partial fills down to 0.03 sh.

### 1.3 Tick-size change — the rule is NOT documented; measured behaviour (agent A, `tickjump/agentA/a12_tick.py`)
- `tick_size_change` WS event `{old_tick_size: "0.01", new_tick_size: "0.001", timestamp}` per token.
- Measured on 16,212 raw events: the flip arrives **~121 s (p50) after the favourite first prints above 0.96; 74 % of
  flips are after the bar closes; 13 % of decisive bars have it by tl 30**. No doc page (place-orders, market-details,
  prices-orderbook, order-lifecycle, changelog) describes the trigger. Working model: operator/cron-driven repricing on a
  ~2-minute cadence keyed on price, not an engine-level price trigger. **Consequence: sub-cent prices are legal mostly
  in the POST-CLOSE window** (§2a). ⏳ re-measured below on the rebuilt `tick_raw.jsonl`.

### 1.4 Fees and the maker rebate (docs: trading/fees.md, programs/maker-rebates.md; live gamma)
- `fee = C · rate · p · (1−p)`, crypto `rate 0.07`, `takerOnly: true`, **makers never pay**; rounded to 5 dp, min 0.00001.
- **Maker Rebates Program** (docs, exact): *"rebate = (your_fee_equivalent / total_fee_equivalent) × rebate_pool"*, per
  market category, paid **daily in pUSD, min $1**. Crypto pool = **20 %** of category taker fees. Because the pool is 20 %
  of the same total that the ratio divides by, this is **algebraically identical to 20 % of your own fill's
  fee-equivalent** — which is what E7's receipt showed (20.0 %, no dilution). The rebate-farm doc §0 and the docs agree;
  the "pool" wording is not a pro-rata dilution. Live: every 5m/15m crypto market `feeSchedule {rate 0.07, exponent 1,
  takerOnly true, rebateRate 0.2}`, `makerRebatesFeeShareBps 10000`.
- **No maker tier / loyalty / volume program exists.** The **Taker Rebate Program** (live 2026-05-28) is 7 tiers on 30-day
  weighted volume `wV = size × (1−entry) × category weight (crypto 2.3)`, Bronze $2k→3 % … Obsidian $10M→50 %;
  *"Only taker trades earn Weighted Volume … Maker trades do not count."* ⇒ maker volume buys nothing anywhere.

### 1.5 Liquidity rewards (docs: programs/liquidity-rewards.md; live gamma)
- Score `S(v,s) = ((v−s)/v)² · b`, `v` = max spread, `s` = distance from the *size-cutoff-adjusted midpoint* (rule not
  specified); `Q_one` = bids on market + asks on complement, `Q_two` the reverse, **`Q_min = min(Q_one, Q_two)`**; single-
  sided scores ÷3 when the midpoint is in [0.10, 0.90], **must be double-sided outside it**; sampled every minute,
  normalised per sample across all makers, summed over a 10,080-minute epoch; paid **daily at 00:00 UTC, min $1**.
- The **$1M crypto-TWAP program (5m $550k: BTC $300k, SOL/ETH/HYPE/XRP $200k, BNB/DOGE $50k; 15m $350k; 4h $100k)
  ran "through August"** and the docs do not say it continues. **Live 2026-09-08: `clobRewards: None` on every 5m/15m
  crypto market; `rewardsMinSize 50`, `rewardsMaxSpread 4.5` remain configured** ⇒ the plumbing is armed, the pool is
  $0. (`tools/mrec/midband/rewards_monitor.py` polls exactly this.)
- No anti-gaming, self-trade, or minimum-rest-time rule is documented anywhere.

### 1.6 Settlement / resolution (docs: market-data/chainlink-twap.md, concepts/resolution.md; changelog)
- Changelog 2026-08-07: crypto up/down resolves on **Chainlink TWAP**; 2026-08-14: **5m = 60-second TWAP** (was 30 s);
  `cryptoMarketConfig {twapEnabled true, twapLookbackSeconds 60}`, `resolutionSource
  https://data.chain.link/streams/<coin>-usd-twap-60s-streams`. Recorder `RES` rows: `post_secs ≈ 305-315 s`.
- ⏳ §1.6 to be completed from resolution.md / chainlink-twap.md / positions-manage.md (redemption, split/merge, relayer).

### 1.7 ⏳ Rate limits, WebSocket channels, error codes, self-trade handling — pending fetches.

---
## 2. THE TWO WINDOWS — ⏳ (post-close improver bid on the known winner; pre-open time priority)
## 3. ABUSE CATALOGUE — ⏳
## 4. RE-CHECK LIST — ⏳
