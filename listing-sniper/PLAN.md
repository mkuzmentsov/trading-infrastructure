# Listing-sniper — plan & investigation

Trading the new-token-listing "pump then bleed" on Binance (spot/perps), with an eye to other
venues later. This doc is the **research + design plan**; nothing is built yet. Methodology is the
same as the rest of the repo: **validate the edge OOS, after realistic costs, before risking money**
— and be honest when the edge is mostly execution luck.

---

## 0. TL;DR — my honest read before we build

- **The phenomenon is real but it is NOT a free lunch.** New listings — especially brand-new,
  low-float / high-FDV tokens — frequently spike in the first minutes then bleed for hours/days.
  But it is one of the **most crowded, most execution-dominated trades in crypto**: snipers,
  market-makers and MM bots are all there at T=0, spreads are enormous, and the "obvious" fade is
  exactly what everyone tries.
- **The edge, if any, lives in execution + selection, not in the pattern itself.** *Which* listings
  pump-and-hold vs dump-from-open (selection), and *being filled at a sane price* (execution), are
  where money is made or lost. This is the same lesson as the polymarket/perp work in this repo:
  the directional "pattern" is well known; capturing it net of slippage/fees/funding is the hard part.
- **So the first deliverable is not a bot — it's the data + a characterization study** that answers
  "is this actually true, for which listings, and how big after costs?" If that survives, *then* we
  build. If it doesn't, we've spent days not dollars.

---

## 1. What actually happens at a Binance listing (domain model)

Three structurally different cases — they behave very differently and must be separated:

| Case | Prior market? | Opening price behaviour | Pump-dump strength |
|------|---------------|-------------------------|--------------------|
| **A. Already trading elsewhere** (Gate/MEXC/KuCoin/DEX) | yes | arbitrage snaps Binance to the existing global price within seconds | **weak** — already priced; mostly a liquidity event |
| **B. Brand-new / Binance-first** (Launchpool, TGE, exclusive) | no/thin | pure order-book price discovery from tick 1; can gap +5–50× then −70/90% | **strong** — the classic pump-bleed |
| **C. Pre-market / call-auction listings** | sometimes | Binance runs a pre-market or opening auction; "the open" isn't a single instant | special-case |

**Implication:** the explosive, tradable pattern is mostly **Case B**. So *step one of selection* is
"is this token genuinely new to the universe, or already liquid elsewhere?" (see §2.3). Lumping all
listings together will wash out the signal.

**Spot vs perp timing matters enormously for the SHORT side:**
- Binance lists **spot** and **USDⓈ-M perp** on separate schedules. For brand-new tokens, spot often
  lists first and the perp comes later (or with a small initial position cap).
- To **short the open pump you need the perp live with liquidity and shortable**, *and* funding can
  be punitive (new-listing perps routinely run +100…+1000% APR funding against shorts). If the perp
  isn't there or shorts are capped/expensive, the short leg of the thesis simply isn't executable.
- The long side is always executable on spot, but exiting into the dump is its own race.

---

## 2. The specific questions you asked — answers + how to verify

### 2.1 Is the "pump then bleed" actually true? → a characterization study (Phase 1)
Don't take it on faith. Build a dataset of historical listings and measure, per listing:
peak return & **time-to-peak**, drawdown from peak, return at +5m/+15m/+1h/+4h/+24h, split by
Case A/B/C. Output: distributions, not anecdotes. **This is the go/no-go gate.**

### 2.2 The announcement feed (verified working)
Binance CMS announcement API — no auth, just a `User-Agent` header:
```
GET https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageNo=1&pageSize=20
```
`catalogId=48` = **New Cryptocurrency Listing**. Returns `data.articles[]` with `id`, `code`,
`title` (title carries the date, e.g. "… (2026-06-29)"). The **exact listing time + spot-vs-perp**
lives in the article body — fetch detail via the `code`:
```
https://www.binance.com/en/support/announcement/<code>
  (or the JSON detail endpoint /bapi/composite/v1/public/cms/article/detail/query?... )
```
Other catalogs worth polling: Futures launches (perp listings), Launchpool, Delistings (for the
survivorship problem in §4). **Other exchanges** (Upbit — the famous "Upbit effect", Coinbase, OKX,
Bybit) have similar announcement feeds; Binance first, add others once the harness exists.

### 2.3 New-to-universe vs already-listed-elsewhere
For each token, at announcement time check whether it already trades widely:
- ccxt across a basket (gate, mexc, kucoin, okx, bybit) → is there an existing `<TOKEN>/USDT` market?
- DEX / aggregator (Dexscreener/GeckoTerminal API) → is there onchain liquidity already?
This single feature is probably the **strongest selector** (Case A vs B). Log it for every listing.

### 2.4 How is the initial price set?
**We don't set it; the market does.** For Case A it arbs to the existing global price almost
instantly. For Case B it's pure order-book discovery from the first trade — no oracle, no formula,
Binance does not "seed" a price. (Some listings use an **opening call auction / pre-market** that
prints the first price from matched pre-orders.) **Design consequence:** the bot must *read the live
book / first prints and react*, never try to predict the open price. Our reference price = the
correct live feed (see §5.2), not a calculated value.

### 2.5 SL/TP — feasible, with a big caveat
Binance supports native stop / take-profit / OCO on both spot and futures. So yes. **Caveat:** in
listing-open volatility, stops **gap through** — a "−10% stop" can fill −30% when the book is air.
Plan for: (a) stops as a *backstop*, not the primary exit; (b) a hard **time-based exit** (e.g. flat
by T+N minutes regardless); (c) marketable-limit exits with a slippage cap (same idea we used in
funding-carry) rather than naked market orders.

### 2.6 Reverse order when the previous closes — feasible (state machine)
e.g. *long the first-minutes momentum → exit at TP/time → flip short the bleed (perp).* Model the
position as a small FSM: `WAIT → LONG → (TP|SL|TIME) → FLAT → [optional] SHORT → … → DONE`. The
reverse leg is gated on perp availability + funding (§1). Idempotent + restart-safe (§5.4).

### 2.7 AI — yes, but Phase 3, and kept modest
Two honest places ML helps; both are **small-data → overfitting-prone**, so they come *after* the
rules baseline:
- **Pre-trade selection classifier**: features known at announcement (new-to-universe, FDV/float if
  available, sector/narrative, BTC regime, time-of-day, which exchange, was-it-Launchpool) →
  P(dumps-from-open) vs P(pumps-and-holds). Universe is only **hundreds of listings over years** →
  use simple, regularized models (logistic/GBT), purged CV, and the Deflated-Sharpe discipline from
  algo-trading-bot. Don't deep-learn 300 rows.
- **Intraday exhaustion classifier**: on the first-minutes tape (returns, volume, book imbalance,
  trade-size distribution) → "follow-through vs fading." Useful but execution-bound.
Start with transparent rules; add ML only where it beats them OOS.

---

## 3. Strategy variants to test (don't assume which works)
1. **Long-momentum**: buy the open, ride the initial spike, exit on time/trailing stop. Pure spot,
   always executable; pays for being late.
2. **Fade-the-pump (short)**: wait for exhaustion signal, short the bleed on the perp. Highest stated
   upside, **least executable** (perp liveness, short caps, brutal funding).
3. **Buy-the-dump (reversion)**: after a −X% bleed from peak, buy the bounce; spot; lower variance.
4. **Selection-only**: only trade Case-B, new-to-universe, within a sector/time filter — the filter
   may matter more than the entry rule.
Each is a different execution profile; the backtest must score them *separately*, with costs.

---

## 4. Data plan (the real work — Phase 0)
- **Listings catalogue**: scrape the announcement API (§2.2) back as far as it serves; parse
  title/body → `{symbol, listing_ts_utc, market=spot|perp, is_launchpool, source_exchange=binance}`.
  Cross-check with third-party listing calendars where the API is thin.
- **Intraday price for the first ~24h of each listing** (the hard part):
  - Binance klines (`/api/v3/klines`, 1m) + `aggTrades` (sub-second) **from the listing minute** —
    available for pairs that still exist.
  - **Survivorship trap**: many pump-dump tokens get **delisted**, and Binance drops their history →
    we lose exactly the worst dumps. Must (a) pull the Delistings catalogue, (b) backfill delisted
    names from another source (a data vendor / archived datasets / another CEX that still lists them),
    or (c) explicitly mark the dataset as survivorship-biased and treat results as an upper bound.
- **New-to-universe label** per token (§2.3), captured *as of the listing date*, not today.
- Store as parquet, same point-in-time store pattern as algo-trading-bot.

## 5. Execution architecture (your design, refined)

### 5.1 Components
- **Announcement watcher** — poll the CMS API every ~5–15 s; diff against seen IDs; on a new listing
  article, fetch detail, parse exact `listing_ts` + spot/perp, persist, alert (optional Telegram).
- **Scheduler** — for each upcoming listing, register a timed job that wakes at `listing_ts − Δ`
  (Δ ≈ a few seconds). Survives restart (re-derive pending jobs from persisted upcoming-listings).
- **Executor (per listing)** — at `T−Δ`: connect the **correct** WS feed, (optionally) pre-build &
  pre-sign orders; at `T`/first-tick: run the chosen strategy FSM (§2.6); manage SL/TP/time/reverse.
- **Optional Telegram** — behind a flag/secret; emits: new listing detected, T−Δ armed, entry fill,
  exit fill, errors. Reuse funding-carry's telegram.py pattern. **Off by default.**
- **Verbose research logging** — every tick/decision/fill to structured JSONL for later analysis
  (this is how we learn what really happens at the open).

### 5.2 Price source — pick the right one
**Futures and spot prices diverge at listings** (the perp can trade at a large premium/discount).
The bot must subscribe to the feed of **the instrument it trades**:
- trading spot → spot `bookTicker`/`aggTrade` WS for `<SYM>USDT`;
- trading perp → USDⓈ-M futures `bookTicker`/`aggTrade` WS for the perp.
Never size/trigger off the other leg's price. (If we ever do cross-leg arb, that's a separate design.)

### 5.3 Order placement
- **Marketable-limit with a slippage cap**, not naked market orders (open spreads are enormous) —
  same discipline we applied to funding-carry. Accept partial fills; never chase to infinity.
- Pre-create the ccxt client + warm the connection before `T` so the entry path is POST-only.
- Idempotent client order ids; reconcile fills against the venue (don't double-count).

### 5.4 Restart safety (learned the hard way on the Kraken bot)
- State (seen-listing ids, pending jobs, open position) on a PVC.
- On restart: reconcile open position + balance **from the venue**, advance the fill cursor to *now*
  so pre-restart fills aren't replayed, re-derive pending timed jobs. `replicas:1 + Recreate`.

### 5.5 Infra
Same k8s dev-bot pattern as the others: small Docker image, Deployment on the Hetzner k3s cluster,
secret for API keys, PVC for state, optional Telegram secret. No GPU.

---

## 6. Risks & honest caveats (read before getting excited)
- **Crowded & decaying** — every sniper does this; the post-2024 "low-float/high-FDV" dump meta may
  already be arbitraged or may shift. Edge is not guaranteed to exist *now*.
- **Execution-dominated** — slippage at the open, partial fills, the perp not being shortable/live,
  punitive funding on shorts, WS/API rate limits and disconnects at the exact worst moment.
- **Listing-time imprecision** — announced times can be vague ("around"), change, or be a
  pre-market/auction rather than a clean instant. The scheduler must tolerate slop.
- **Small sample** — only hundreds of listings ever; easy to overfit a rule or an ML model. Demand
  OOS + Deflated-Sharpe-style significance, not a pretty in-sample curve.
- **Survivorship bias** — delisted dumpers vanish from Binance history; naïve backtests look too good.
- **Account/regulatory risk** — aggressive sniping can trip exchange anti-abuse; keep size sane.
- **Capital at risk is real and fast** — a mistimed long on a token that opens +200% and bleeds −80%
  is a large loss in minutes. Hard caps, time-stops, and tiny live size are mandatory.

---

## 7. Phased roadmap (validate before risking money)
- **Phase 0 — Data**: announcement catalogue + first-24h intraday for each listing + new-to-universe
  labels; handle the delisting/survivorship problem explicitly.
- **Phase 1 — Characterization (GO/NO-GO)**: quantify the pattern by case/type/time. Is it real and
  big enough after a realistic cost model? If not → stop here.
- **Phase 2 — Backtest** the strategy variants (§3) separately, realistic fills/slippage/funding,
  OOS split + Deflated-Sharpe/PBO discipline. Honest verdict.
- **Phase 3 — Forward paper-trade** on *live* upcoming listings (the announcement watcher + executor
  in paper mode): does the live open behave like the backtest? Does our fill model hold?
- **Phase 4 — Tiny live** (a few $ per listing), measure realized vs paper, iterate.
- **Phase 5 — Optional AI** selection/exhaustion models once enough labelled live data exists.
- **Phase 6 — Other venues** (Upbit/Coinbase/OKX) once the Binance harness is proven.

---

## 7b. Phase-1 preliminary finding (built — `scripts/characterize.py`)
First pass over **23 genuine "Binance Will List" spot listings** (survivors only, ~2026 H1):

| metric (median) | value |
|---|---|
| peak return (first day) | **+13%** (time-to-peak ~45 min) |
| drawdown from peak | **−28%** |
| return @ 15m / 1h / 24h | −0% / −3.5% / **−6.3%** |
| end-of-day return | **−9.6%** |
| **share red at 24h** | **74%** |
| "dumped from open" (spike then <open within 1h) | 9% |

**Read:** buying the open and holding is a **losing trade** (74% red @24h); there's a real **downward
drift** + a −28% median bleed from the peak → a *short/fade bias has statistical support*. BUT it's
high-variance with a **heavy right tail** (a few moonshots: CHIP +112%, RE +81% @24h) that would blow
up a naïve short, peak timing is unpredictable (min 1 → min 1392), and this is **survivor-biased**
(delisted −90% dumpers excluded → true downside worse, *helps* the short thesis but those names may
not have had a shortable perp). **Not a slam dunk** — Phase 2 must price the perp short + funding +
survivorship before any money. Naïve long-the-open is rejected already.

## 7c. Phase-2 input — the perp + funding (built — `scripts/characterize_perp.py`)
The short is the actionable side, so we checked the USDⓈ-M perp + funding for the same listings (21
with a perp, survivors):

| metric (median, perp) | value |
|---|---|
| perp peak_ret / drawdown-from-peak | +10.8% / −25.2% |
| perp red @ 24h | **52%** (vs spot 74%) |
| **perp-vs-spot listing lag** | **−5.6 days** (only **10%** list spot+perp simultaneously) |
| funding to a short over 24h | **+0.12%** median; **67% of perps PAY the short**; worst −10.8% |

**Key insight (reshapes the whole thesis):** most "Binance Will List" *spot* announcements are for
tokens that **already traded as a Binance perp days earlier** — so the spot "open" is *continuation*,
not fresh price discovery, and the spot "74% red" was inflated by it. On the perp itself the drift is
**weaker (52% red)** and carries the **same moonshot right tail** (TRUMP +237%, ASTER +99% @24h) that
liquidates a naïve short. Funding is a *mild tailwind* for shorts (67% pay the short) but with a nasty
squeeze tail (−10.8%). **Conclusion:** the only genuinely tradeable population is the slice where
**spot+perp list simultaneously (lag≈0 = truly new tokens)** — Phase 2 must filter to that subset and
re-characterize, then size the short for the right tail. The naïve "short every listing" is not it.

## 7d. VERDICT (Phase-1 GO/NO-GO) — the easy thesis is a mirage ⛔
Full dataset (`scripts/build_dataset.py` → 132 'Will List' listings, 2020-2026; analysed by
`characterize.py`), split by perp-vs-spot **lag** (our proxy for 'already priced'):

| bucket | n | spot ret@24h | red@24h | perp red@24h | short funding/24h |
|--------|---|--------------|---------|--------------|-------------------|
| ALL (conflated) | 132 | −10% | 76% | 55% | +0.12% |
| **GENUINELY-NEW** (spot+perp ≤60m) | **8** | **+1.7%** | **38%** | **50%** | **−0.56% (short PAYS)** |
| CONTINUATION (perp predates spot) | 95 | −11.3% | 75% | 56% | +0.12% |

**The headline "short the listing → 76% red" is ENTIRELY a CONTINUATION artifact** — tokens already
trading as a perp for days, just gaining a spot market. That is not a listing trade; it's shorting an
already-priced token (no edge from the listing, available any day).

**For genuinely-new tokens** (the actual idea): median **+1.7%** @24h, only **38% red**, the perp a
**coin flip (50%)**, the short **pays** funding (−0.56%, worst −10.8%), and a heavy moonshot tail
(RE +80%, APE +59% @24h) that liquidates a short. There are only **~8 such listings in 6 years**
(~1/yr) — even with an edge, the opportunity count is negligible. Add survivorship bias (delisted
dumpers gone → if anything the genuinely-new short looks *better* than reality) and it's worse.

**Recommendation: NO-GO on the executor as originally imagined** (short the new-listing dump). The
data does not support it. Honest residual angles, all weak / small-sample, *not* worth building now:
- first-**minutes** fade (we have 1m data; 24h horizon may hide a brief early fade) — but tiny-N + execution-bound;
- **long**-momentum on genuinely-new (+33% median peak) — but ~1/yr and huge variance.

What this exercise *did* deliver: a clean, tested data harness (announcement feed + dataset +
characterization) that **answered the question for ~$0 and zero risk** — which is the whole point.

## 8. Suggested first concrete steps
1. `announcement_watcher.py` — poll the CMS API, parse new listings (symbol, ts, spot/perp), persist
   + log. (Also doubles as the live feed for Phase 3.) **Cheap, high-value, do this first.**
2. `build_listings_dataset.py` — backfill the historical catalogue + first-24h klines, with the
   new-to-universe label and the delisting/survivorship handling.
3. `characterize.py` — the Phase-1 study (distributions, by case/type). **The go/no-go.**

If you're happy with this plan, I'd start with #1+#2 (data) — that's what tells us whether there's
anything here worth building a bot around.
