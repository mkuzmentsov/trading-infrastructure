---
name: project-funding-carry-hl-order-fixes-2026-05-18
description: Three-bug fix chain that made funding-carry actually open HL shorts (sub-account routing, swallowed responses, price tick)
metadata:
  type: project
---

funding-carry could not open HL shorts on a sub-account. Three stacked bugs, found and fixed in order on 2026-05-18:

1. **Sub-account not routed.** `HyperliquidPerp` only passed `account_address` to the SDK `Exchange`; never `vault_address`. On HL, `account_address` is only the agent→master mapping — orders route to a sub-account ONLY when the signed action carries `vaultAddress`. Orders were silently executing against the empty master. Fix mirrors `trading-mcp/src/trading_mcp/exchanges/hyperliquid.py:145-160`: `account_address`=MASTER (signing root), `vault_address`=sub (routing + reads target the sub). Added `vault_address` to `bot/exchanges.py`, `bot/main.py` (coerce/validate/pass-through), `config*.yaml`, chart `values.yaml`. Overlay `helm/bots/fc_top1_200.yaml` was already correctly split (master `0xD17E…`, sub `0x65ce…2156`) — code just ignored the field.

2. **Swallowed HL responses → naked spot.** `_send()` did `return fn()` with no inspection; `main.py:220` discarded `open_short()`'s return and ran the Kraken buy unconditionally on the next line. A rejected short looked identical to a fill and left a naked Kraken long. Fix: added `_interpret()` (parses `statuses[].filled/resting/error`, top-level `status`; non-order actions like `set_leverage` have no statuses → accepted), `_send()` logs `HL OK`/`HL REJECTED` and raises new `HLOrderError`; `open_pair` catches it and skips the Kraken leg.

3. **Invalid price.** Raw `px*(1-slip)` float (e.g. `9.453603849999999`) passed straight to the SDK → `error: Order has invalid price`. HL needs ≤5 sig figs AND ≤(6−szDecimals) decimals for perps (integers exempt). Added `_round_px()` = `round(float(f"{px:.5g}"), 6-szDec)`, applied in open/reduce/close_short. `:.5g` collapses large prices (105000.5→105000.0 integer, exempt) so no special-casing needed.

**Why:** delta-neutral carry MUST leg HL-first and atomically; a swallowed rejection or unrouted order breaks neutrality silently.
**How to apply:** any new HL action wrapper goes through `_send` (gets response-checking + raise free); price args must pass `_round_px`. Deploy: `cd funding-carry/k8s/helm && ./deploy.sh fc_top1_200` (rsyncs `bot/*.py`; stale `files/bot/` copies refresh on deploy). Still owed: confirm agent `0x980e…` is approved on master `0xD17E…` and `0x65ce…2156` is a registered sub — use trading-mcp `hyperliquid_check_auth`. See [[project-funding-carry-deploy-chart-2026-05-13]] and [[project-trading-mcp-profit-maximization-2026-05-14]].
