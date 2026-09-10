# trading-mcp operating prompts

Reusable prompts to drive the `trading` MCP as the strategy brain (no bot loop). Paste into
Claude (Desktop / CLI / web) with the `trading` connector attached, or use as the body of a
scheduled routine.

| File | Mode | What it does |
|------|------|--------------|
| [01-analyze-funding-carry.md](01-analyze-funding-carry.md) | read-only | Snapshots the live carry, computes effective APR + realized PnL, scans all venues for a better funding+earn combo, and recommends HOLD vs SWITCH with breakeven math. |
| [02-open-rotate-position.md](02-open-rotate-position.md) | executes (confirm-gated) | Closes any existing carry, fee-aware stablecoin rebalance across venues, opens a new delta-neutral carry, subscribes flex Earn. Dry-run first, executes on "confirm". |
| [03-polymarket-scan-edges.md](03-polymarket-scan-edges.md) | read-only | Scans Polymarket's four lanes — reward pools, neg-risk baskets, combos, cheap longshots — against real books, and returns GO/NO-GO per lane. |
| [04-polymarket-farm-rewards.md](04-polymarket-farm-rewards.md) | executes (confirm-gated) | Arms ONE liquidity-reward pool with a minimum two-sided post-only quote, then verifies it is actually scoring. Dry-run first. |
| [05-polymarket-cheap-bets.md](05-polymarket-cheap-bets.md) | executes (confirm-gated) | Builds a cheap asymmetric-payoff slate: screen, read resolution rules verbatim, check whale flow, size as lottery tickets. |

Conventions both prompts follow:
- **Concise output** — verdict first, a table, no narration.
- **Dated output** — every report begins with today's UTC date for logging. (The MCP itself
  doesn't emit a timestamp yet; add a `get_server_time` tool / `funding_carry_status.server_time`
  field if scheduled runs shouldn't trust the model's clock.)
- **Delta-neutral always** — legs quantity-matched; never a naked directional leg between steps.
- **Flex Earn only** — instant-unstake so the hedge stays exit-able.
- **Favorable entry basis** — legs are quoted before opening; a carry only fires when the perp
  shorts at ≥ the spot we buy (or within 5 bps), so it never starts underwater.
- **Fee-gated** — transfers/rotations only fire when the benefit beats withdrawal+network fees;
  every withdraw/order is a dry-run before a confirmed execution.

Typical cadence: run **01** (e.g. daily), and only run **02** when 01 says SWITCH or you want to
open from flat. For Polymarket: run **03** to find a target, **04** to arm a reward pool, **05** for
a cheap-bet slate. Re-run **03** every few days — reward pools open and close, and an empty band
fills as soon as someone else notices it.

Polymarket prompts additionally assume:
- **Real books only** — availability is read via `polymarket_get_books`, never gamma's cached
  `bestBid`/`bestAsk`, which have shown ghost quotes.
- **Maker-only by default** — `execution="maker"` is post-only, so it cannot cross: zero taker fee
  and reward-eligible. Taker is reserved for an explicitly time-critical thesis.
- **Net of fees or it isn't an edge** — `rate × p × (1−p)` per share cancels a 1c gross basket edge
  exactly. Geopolitics is the one fee-free category.
