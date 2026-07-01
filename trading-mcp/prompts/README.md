# funding-carry operating prompts

Reusable prompts to drive the `trading` MCP as the strategy brain (no bot loop). Paste into
Claude (Desktop / CLI / web) with the `trading` connector attached, or use as the body of a
scheduled routine.

| File | Mode | What it does |
|------|------|--------------|
| [01-analyze-funding-carry.md](01-analyze-funding-carry.md) | read-only | Snapshots the live carry, computes effective APR + realized PnL, scans all venues for a better funding+earn combo, and recommends HOLD vs SWITCH with breakeven math. |
| [02-open-rotate-position.md](02-open-rotate-position.md) | executes (confirm-gated) | Closes any existing carry, fee-aware stablecoin rebalance across venues, opens a new delta-neutral carry, subscribes flex Earn. Dry-run first, executes on "confirm". |

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
open from flat.
