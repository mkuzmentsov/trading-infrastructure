# trading-mcp

Multi-exchange MCP server. Each exchange's tools live in their own module under `src/trading_mcp/exchanges/` and register themselves only when their API credentials are present in `.env`.

| Exchange     | Status        | Tool prefix     |
|--------------|---------------|-----------------|
| Binance      | ✅ implemented | `binance_*`     |
| Kraken       | ✅ implemented | `kraken_*`      |
| Hyperliquid  | ✅ implemented | `hyperliquid_*` |
| WhiteBIT     | ✅ implemented | `whitebit_*`    |

Plus a **cross-venue aggregator** (no prefix) that fans out to every configured
exchange — `find_best_yield_anywhere`, `find_cheapest_borrow`,
`compare_perp_funding`, `get_total_nav`, `funding_carry_screener`,
`find_best_promotions`.

Runs locally as a Docker Compose service over streamable-HTTP. Claude Desktop attaches via the `mcp-remote` bridge.

---

## 1. Configure your API keys

```bash
cd trading-mcp
cp .env.example .env
$EDITOR .env   # fill in keys for the exchanges you want to enable
```

You only need to populate the exchange blocks you care about — leaving keys blank skips that exchange entirely.

**Binance permissions** (set on https://www.binance.com/en/my/settings/api-management):

| You want to…                  | Enable                       |
|-------------------------------|------------------------------|
| Read balances / Earn rates    | Read only                    |
| Spot / Margin trading         | Enable Spot & Margin Trading |
| USDⓈ-M / COIN-M Futures      | Enable Futures               |
| Withdraw to whitelisted addr  | Enable Withdrawals           |

IP-whitelist your API keys to your machine's egress IP for safety.

The `binance_withdraw` tool is gated by a `confirm=True` flag — a dry-run is returned first so Claude has to explicitly re-issue with confirmation.

## 2. Start the server

```bash
docker compose up -d --build
docker compose logs -f trading-mcp
```

It binds to `127.0.0.1:8765` (loopback only — not reachable from the LAN). On startup it logs which exchanges were registered:

```
INFO trading-mcp: Registered 33 tools from trading_mcp.exchanges.binance
INFO trading-mcp: Registered 6 tools from trading_mcp.exchanges.kraken
INFO trading-mcp: Registered 18 tools from trading_mcp.exchanges.hyperliquid
INFO trading-mcp: Registered 5 tools from trading_mcp.exchanges.whitebit
INFO trading-mcp: Registered 6 tools from trading_mcp.exchanges.aggregator
```

Unconfigured exchanges register 0 tools and log `Skipped …`. The aggregator
always registers — its tools internally degrade per-venue.

## 3. Wire it into Claude Desktop

Claude Desktop launches MCP servers via stdio, so we use [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) as a bridge.

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "trading": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp"]
    }
  }
}
```

Restart Claude Desktop. The hammer-icon tool menu should now list tools like `binance_get_portfolio_overview`, `binance_find_best_earn_rates`, `binance_place_spot_order`, …

## 4. Tools by exchange

### Binance (33)

**Portfolio:** `binance_get_portfolio_overview`

**Market data:** `binance_get_price`, `binance_get_klines`

**Spot:** `binance_get_spot_balances`, `binance_get_spot_open_orders`, `binance_place_spot_order`, `binance_cancel_spot_order`, `binance_get_spot_trade_history`

**USDⓈ-M Futures:** `binance_get_futures_account`, `binance_get_futures_positions`, `binance_get_futures_open_orders`, `binance_place_futures_order`, `binance_cancel_futures_order`, `binance_set_futures_leverage`, `binance_set_futures_margin_type`, `binance_get_futures_funding_rate`

**COIN-M Futures:** `binance_get_coin_futures_account`, `binance_get_coin_futures_positions`, `binance_place_coin_futures_order`, `binance_cancel_coin_futures_order`

**Margin:** `binance_get_margin_account`, `binance_margin_borrow`, `binance_margin_repay`, `binance_place_margin_order`

**Simple Earn:** `binance_list_earn_flexible_offers`, `binance_list_earn_locked_offers`, `binance_find_best_earn_rates`, `binance_get_earn_flexible_positions`, `binance_get_earn_locked_positions`, `binance_subscribe_earn_flexible`, `binance_subscribe_earn_locked`, `binance_redeem_earn_flexible`, `binance_redeem_earn_locked`

**Transfers:** `binance_universal_transfer`, `binance_get_transfer_history`

**Deposits / withdrawals:** `binance_get_deposit_address`, `binance_get_deposit_history`, `binance_get_withdraw_history`, `binance_withdraw` (dry-run unless `confirm=True`)

**Promotions:** `binance_list_promotions`

### Kraken (6)

**Balances:** `kraken_get_balances`, `kraken_get_balances_ex`

**Earn:** `kraken_list_earn_strategies`, `kraken_list_earn_allocations`, `kraken_get_earn_allocation_status`, `kraken_find_best_earn_rates`

### Hyperliquid (18)

**Market data:** `hyperliquid_get_meta`, `hyperliquid_get_spot_meta`, `hyperliquid_get_all_mids`, `hyperliquid_get_funding_rates`, `hyperliquid_get_funding_history`

**Account:** `hyperliquid_get_perp_account`, `hyperliquid_get_spot_balances`, `hyperliquid_get_open_orders`, `hyperliquid_get_fills`, `hyperliquid_get_user_funding_payments`, `hyperliquid_get_vault_equities`, `hyperliquid_get_hlp_summary`

**Trading:** `hyperliquid_place_perp_order`, `hyperliquid_market_close_position`, `hyperliquid_cancel_perp_order`, `hyperliquid_set_leverage`

**Transfers:** `hyperliquid_bridge_usdc`, `hyperliquid_vault_transfer` (dry-run unless `confirm=True`), `hyperliquid_withdraw_usdc` (dry-run unless `confirm=True`)

**Discovery:** `hyperliquid_find_best_funding_rates`

> HLP vault address is hard-coded as the default for `hyperliquid_vault_transfer`. HLP has a **4-day unlock period** from the most recent deposit — verify before subscribing.

### WhiteBIT (5)

**Balances:** `whitebit_get_main_balance`, `whitebit_get_trade_balance`, `whitebit_get_collateral_balance`

**Fees:** `whitebit_get_fee_schedule`

**Smart Staking:** `whitebit_smart_staking_info` (returns a link — no REST API exists)

### Aggregator (6)

Cross-venue tools that pick up whichever exchanges have credentials and merge the answer:

- `find_best_yield_anywhere(asset, top_n)` — best APR across Binance Simple Earn (flex+lock), Kraken Earn, Hyperliquid HLP.
- `find_cheapest_borrow(asset)` — Binance Cross-Margin daily borrow rate (annualized). More venues land here when added.
- `compare_perp_funding(coin)` — current funding APR side-by-side: Hyperliquid + Binance USDⓈ-M. Reports the max-spread funding pair.
- `get_total_nav(idle_threshold_usd)` — best-effort USD NAV summed across every venue + stablecoin balances ≥ threshold that are sitting *outside* any Earn product.
- `funding_carry_screener(top_n, min_oi_usd)` — ranks Hyperliquid perps by `|funding APR| × liquidity` for funding-carry basket candidates.
- `find_best_promotions(keywords)` — sweeps Binance announcement feed for airdrops / Launchpool / Megadrop / competitions.

## 5. Adding a new exchange

1. Create `src/trading_mcp/exchanges/<name>.py` with a `register(mcp: FastMCP) -> int` that:
   - returns `0` early if its credentials aren't in env (so the server still starts)
   - defines each tool inside the function with `@mcp.tool()` and an `<name>_*` prefix
   - returns the number of tools registered
2. Import and add the module to the loop in `src/trading_mcp/server.py::_register_all`.
3. Add the env block to `.env.example`.
4. `docker compose up -d --build`.

## 6. Operating notes

- Container restart policy is `unless-stopped`; survives reboots.
- `BINANCE_TESTNET=true` routes Binance to testnet — useful when first wiring this up.
- Logs: `docker compose logs -f trading-mcp`.
- Code changes: `docker compose up -d --build`.
- Stop: `docker compose down`.

## 7. Security

- All credentials live only in `.env` on your machine; `.env` is git-ignored and Docker-ignored.
- Port bound to `127.0.0.1` only — no LAN exposure.
- Binance withdrawals require a second confirmed call.
- Treat the MCP as an extension of your trading session: anything Claude can do, the API keys allow.
