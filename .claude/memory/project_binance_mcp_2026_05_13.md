---
name: project-binance-mcp-2026-05-13
description: binance-mcp/ — local MCP server exposing Binance Spot/Futures USDⓈ-M+COIN-M/Margin/Simple Earn/withdrawals to Claude Desktop via streamable-HTTP + mcp-remote bridge
metadata:
  type: project
---

New project at `binance-mcp/` (sibling of `funding-carry/`, `polymarket/`).

**Shape:** FastMCP (`mcp[cli]`) server + `python-binance` client, Dockerized, runs as a single `docker compose` service binding `127.0.0.1:8765`. Claude Desktop connects via `npx mcp-remote http://127.0.0.1:8765/mcp`.

**Why:** User wants conversational Binance management — balances, trades, current Earn APRs, transfers, withdrawals — driven from Claude Desktop on local machine.

**How to apply:**
- All tool surface lives in `src/binance_mcp/server.py` (one file by design — easy to extend per request).
- `withdraw` is dry-run unless `confirm=True` is passed. Don't remove that gate.
- `find_best_earn_rates` sorts Simple Earn flexible+locked product lists by APR — call when user asks "where can I park X coin best".
- Compose binds loopback only; do not change to `0.0.0.0:8765` without discussing exposure.
- API key creds live in `binance-mcp/.env` (git-ignored, docker-ignored).

**Untested:** never actually started the container — no API key on hand. python-binance Earn method names (`get_simple_earn_account_summary`, `subscribe_simple_earn_flexible_product`, etc.) are wrapped in try/except in `get_portfolio_overview` but raw in the dedicated tools; if user reports `AttributeError`, bump `python-binance` in `pyproject.toml` and/or rename to the version's actual method.

**Deploy:** `cd binance-mcp && cp .env.example .env && $EDITOR .env && docker compose up -d --build`.
