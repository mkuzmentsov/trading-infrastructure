---
name: PM BTC re-entry bid-drop guard 2026-04-23
description: New `blockReentryIfBidDropGt` knob blocks cascade re-entries when same-direction bid collapsed since prior exit. Adds +$16.52/+6.6% on top of skim/thesis tuning winner.
type: project
---

## Motivation
After deploying the skim/thesis-break tuning winner (~+27% replay PnL), live still saw cascade losses. Analysis of bundles `pm-btc-logs_pm-btc-smart_2026042{1,2,3}_*`:
- 41 cascades across 5 bundles, ~50% win rate (vs ~70% single-entry)
- Losing cascades sum to **−$106.88**
- Top-15 worst sum to **−$102.59**

3 distinct failure patterns:
1. Re-entry after THESIS_BREAK or large salvage
2. Kelly-sized inflation (entry sizes grow 19→24→31→38 shares as price drops)
3. Whipsaw recovery (rare but real positive case)

## Sweep results

Tested 24 conditional re-entry blocks. **Sharp non-monotonic threshold curve on bid-drop:**

| Variant | Δ vs winner | Why |
|---|---|---|
| `BLOCK_REENTRY_IF_BID_DROP_GT=0.10` | **+$16.52** | only fires on real bid collapses |
| `BLOCK_REENTRY_IF_BID_DROP_GT=0.07` | +$15.53 | nearly identical |
| `BLOCK_REENTRY_IF_BID_DROP_GT=0.05` | −$3.61 | catches good wobble cascades — too tight |
| `BLOCK_REENTRY_IF_BID_DROP_GT=0.03` | −$3.61 | even tighter — hurts more |
| `BLOCK_REENTRY_AFTER_REASONS=late_bar_salvage` | −$40.82 | nukes all cascades |
| `BLOCK_REENTRY_IF_LAST_LOSS_LT=-3` | −$25.16 | too aggressive |
| `BLOCK_REENTRY_IF_SIZE_MULT_GT=1.5` | +$9.57 | helps less than bid-drop |
| `BLOCK_REENTRY_IF_ADVERSE_BTC_GT=0.0005` | +$2.48 | mild signal |

Per-bundle effect of `biddrop_10`:
| Bundle | Before | After | Δ |
|---|---|---|---|
| 20260421_091646 | +$34.39 | +$35.52 | +$1.13 |
| 20260422_075143 | +$75.78 | +$71.58 | −$4.20 |
| 20260422_212413 | −$4.25 | **+$2.19** | **+$6.44** |
| 20260423_110659 | +$115.12 | **+$128.27** | **+$13.15** |
| 20260423_125531 | +$27.63 | +$27.63 | 0 (filter doesn't fire) |

Net: $248.67 → $265.19, **+6.6%** on top of the prior +27% winner.

## Cumulative improvement vs original baseline

- Original (default config): ~$229.75 (4-bundle subset)
- Skim/thesis winner: $277.59 (+$47.84, +21%)
- Skim/thesis + biddrop_10: ~$293.91 (+$64.16, +28%)

## Key insight
The bid-drop magnitude is the cleanest "cascade is bad" signal. Exit-reason-based blocks are too noisy (good cascades also salvage). Loss-size blocks hit too many cases. Size-inflation works but redundantly with bid-drop. The threshold has a sweet spot at 0.07–0.10 because:
- < 0.05: catches tiny wobbles (good cascades that recover)
- 0.07–0.10: only triggers on real bid collapses (failed thesis)
- > 0.10: misses some failed cases

## Files changed for deployment

1. **`polymarket/k8s/helm/polymarket-btc-bot/files/scripts/config.py`** — added `BLOCK_REENTRY_IF_BID_DROP_GT` env var (default 0 = disabled).
2. **`polymarket/k8s/helm/polymarket-btc-bot/files/scripts/main.py`**:
   - Imported `BLOCK_REENTRY_IF_BID_DROP_GT`
   - Added module-level `_last_exit_bid_by_dir: dict[(cid,dir), float]`
   - Populates on all 4 close paths (recovery-on-restart, normal sell, dry-run, FAK-fill)
   - Added entry-side filter in `_try_enter` after the existing stop-loss reentry guard
   - Added stale-key cleanup at bar boundary alongside existing guard cleanup
3. **`polymarket/k8s/helm/polymarket-btc-bot/templates/secret.yaml`** — exposes `BLOCK_REENTRY_IF_BID_DROP_GT` env from `bot.blockReentryIfBidDropGt` value.
4. **`polymarket/k8s/helm/bots/pm_btc_smart.yaml`** (gitignored, local) — added `blockReentryIfBidDropGt: "0.10"`.

YAML auto-wires via `apply_yaml_to_env` camelCase→SCREAMING_SNAKE conversion (no manual mapping needed).

## How to deploy

```bash
cd polymarket/k8s/helm
helm upgrade --install polymarket-btc-bot ./polymarket-btc-bot \
  -f bots/pm_btc_smart.yaml -n polymarket
```

To disable post-deploy: set `blockReentryIfBidDropGt: "0"` in YAML (or `BLOCK_REENTRY_IF_BID_DROP_GT=0` env override).

## Caveats
- 5-bundle sample, ~46h of trading. Same overfit caveats as prior sweeps.
- `20260423_125531` showed 0 effect — the cascade there had re-entries within 1s of exit (no time for bid to drop further). Filter doesn't address rapid-fire same-bid cascades. Those would need a separate intervention (e.g. cooldown or in-bar salvage tightening).
- Filter is symmetric across UP/DOWN directions but tracks per-direction. It does NOT block opposite-direction entries (correct behavior — opposite direction is a separate thesis).
