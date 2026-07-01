# trading-mcp — improvement backlog

## ✅ Shipped in v0.4 (2026-07-01)
- **BBO/orderbook tools** — `hyperliquid_get_orderbook`, `binance_get_orderbook`,
  `binance_get_futures_orderbook`, `kraken_get_orderbook` (best bid/ask, spread bps, USD depth).
- **`carry_basis(coin, notional, short_venue, long_venue)`** — the entry-basis tool from real
  books (taker + maker bps + depth-absorbs check). Replaces the manual curl. Tested: SUI −3.79 taker.
- **`hyperliquid_get_accounts_overview`** — master + sub value/positions in one call.
- **`kraken_get_withdraw_addresses`** — fixed the list/dict validation crash.
- **`binance_get_futures_account`** — trimmed to totals + non-zero assets/positions (was 308k chars).
- **`kraken_wallet_transfer`** — spot↔futures internal transfer (fund KF margin without a withdrawal).
- **`kraken_find_best_earn_rates`** — `apr_suspect`/`apr_note` flags + `can_allocate` surfaced.

## ✅ Also shipped in v0.5 (2026-07-01)
- **`plan_transfer(asset, amount, from, to)`** — cross-venue transfer planner: source networks +
  fees (cheapest first), receiving deposit address, Kraken whitelist status. Read-only.
- **`binance_get_withdraw_networks`** + **`kraken_get_withdraw_methods`** — fee/network lookup
  before whitelisting.
- **`get_server_time`** — authoritative UTC for dating reports.
- **`kraken_futures_get_orderbook`** + **`whitebit_get_orderbook`** — BBO coverage now all venues.
- Prompt 02: funding-relative basis gate (via `carry_basis`) + pre-flight readiness check.

## Still open (low priority)
- HL funding / poll-until-credited helper (partly covered by `hyperliquid_get_accounts_overview`).
- Destination-address allowlist in config (fat-finger guard on withdrawals).

---

Suggestions distilled from actually running the funding-carry flow end-to-end
(analyze → fund venues → cross-venue transfers → open). Each item notes what we
hit. Priority: **P0** = blocked a live step, **P1** = real friction, **P2** = nice-to-have.

## Tool bugs (fix first)

- **P0 — `kraken_get_withdraw_addresses` is broken.** Returns a JSON *list*, but the
  tool validates against a dict → pydantic `dict_type` error. We couldn't list
  whitelisted addresses, so we couldn't confirm/choose a Kraken→Binance route
  programmatically (had to eyeball a screenshot). Fix the return model.
- **P1 — `binance_get_futures_account` returns 308k chars** and blows the token cap.
  Trim server-side to non-zero assets + totals (`totalWalletBalance`,
  `availableBalance`, open positions), like the other balance tools.
- **P1 — Kraken earn `apr_estimate` is unreliable.** `kraken_find_best_earn_rates`
  surfaced BTC "instant 10% / bonded 15%" when the real allocatable rate was
  **2.1%**. Don't trust `apr_estimate` blindly: prefer a realized/`reward`-based
  field, require `can_allocate=true`, and sanity-bound (a non-PoS asset like BTC
  showing >5% is a red flag → mark "unverified").

## Missing tools / capabilities

- **P0 — per-venue orderbook / best bid-ask (BBO).** There is no clean tool to get
  the executable top-of-book per venue, so the entry-basis calc is wrong-by-design:
  we used HL's **mark** (`hyperliquid_get_all_mids` returns mid only, no bid/ask) and
  a **manual curl** to Binance's public API. A short cares about the HL **bid**
  (where we sell) vs the Binance **ask** (where we buy) — comparing marks/mids
  understates the real entry cost (on ENA, one tick ≈ 14 bps). Add:
  - `*_get_orderbook(coin, depth)` and/or `*_get_bbo(coin)` for HL perp, Binance
    spot+perp, Kraken spot+futures, WhiteBIT (HL SDK `l2_snapshot`; Binance/Kraken
    public depth endpoints — no auth needed).
  - Feed the basis gate + marketable-limit sizing from BBO, and estimate slippage
    for a given size from depth. Fix `aggregator_compare_buy_sell_prices` to use it
    (and to actually price Kraken — see below).

- **P0 — read BOTH master and sub HL accounts.** `hyperliquid_get_perp_account`
  only reads the configured (sub) account. A deposit from the master credited the
  **master**, so the sub showed $0.28 and we nearly opened with no collateral.
  Add an account arg (or return master + all subs), and auto-warn "collateral is
  on master, not the trading sub — transfer first."
- **P1 — cross-venue transfer planner.** One tool: "move $X USDT/USDC from A→B" →
  picks the cheapest network both sides support, checks whitelist status + key
  withdraw permission, returns the destination deposit address + fee, then executes
  on confirm. We did all of this by hand (futures→spot transfer, pick network,
  whitelist, dry-run, withdraw).
- **P1 — withdrawal-fee-by-network lookup.** Kraken has a WithdrawMethods endpoint;
  expose it so we can pick the cheapest network *before* whitelisting (we only saw
  fees via the post-whitelist dry-run, or a phone screenshot). We also mis-guessed
  Arbitrum as cheapest when Kraken charges 2 USDT there vs 0.46 for ERC20.
- **P1 — Kraken spot↔futures internal transfer.** No tool; blocks all-Kraken carries
  (had to route around it). Kraken has a wallet-transfer endpoint.
- **P1 — HL funding helper.** Funding HL from a CEX needs a self-custody Arbitrum
  hop (CEX can't deposit directly). Add a guided helper: correct bridge address,
  USDC-only reminder, and a "poll until credited" that watches master then sub.
- **P2 — `get_server_time`.** Prompts date reports off the model clock; an
  authoritative server timestamp makes scheduled/cloud runs trustworthy.
- **P2 — spot-book coverage in `aggregator_compare_buy_sell_prices`.** It couldn't
  price **Kraken spot** (the `XBTUSDT` pair code returns empty; many alts are
  USD-only on Kraken with no USDT pair). Fix the pair resolver and return
  "pair unavailable" instead of silently skipping.

## Process / gate improvements (prompts)

- **P1 — make the entry-basis gate funding-relative.** The flat −5 bps gate wrongly
  blocked a −11 bps entry against 14.6% funding (pays back in ~3 days). Change to
  "basis recoverable by funding within ≤N days (e.g. 7)."
- **P1 — pre-flight readiness check** before any open: collateral on the right HL
  account (sub, not master), long-leg funds present, whitelist + key-withdraw
  permission set. We discovered each serially mid-flow.
- **P1 — surface `can_allocate` + earn eligibility.** Kraken alt earn showed
  `can_allocate:false` (region), so counted-on earn was actually 0. Make the
  analysis exclude non-allocatable earn up front.
- **P2 — tax-aware routing (Ukraine).** Prefer USDT/crypto-to-crypto legs; flag
  crypto→fiat (Kraken alts are USD-only) so we don't trigger a fiat conversion.
- **P2 — generalize `funding_carry_status`.** It assumes HL-short + Kraken-spot;
  the real book spans HL/Binance/KF shorts and Binance/Kraken longs. Reconstruct
  from whatever legs exist.

## Monitoring / ops (once a carry is live)

- **P1 — carry monitor tool.** Given an open carry: report delta drift
  (|spot−perp|/perp), HL liq room, funding accrued vs fees, and suggest a rebalance
  when delta exceeds a band. Today this is manual.
- **P2 — destination allowlist in config.** Withdraw tools are confirm-gated (good);
  add a config allowlist of known-good addresses to prevent fat-finger sends.
- **P2 — HL funding-rate stability.** KF funding via `relativeFundingRate×24×365`
  is a spiky snapshot (FARTCOIN 127%, HYPE 59%). Expose a short trailing average /
  the prediction field so we don't chase a rate about to mean-revert.
