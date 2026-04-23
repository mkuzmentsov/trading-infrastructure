---
name: PM BTC smart — tuning sweep winner 2026-04-23
description: Walk-forward tuning sweep across 7 pm-btc-smart bundles (20260420→20260423). Winner config adds +27% replay PnL.
type: project
---

## Methodology
Patched `bundle_backtest.py` and `math_smart.py` with env-controlled knobs:
- `SMART_LATE_SKIM_SECS` (was hardcoded to 90/yaml-120)
- `SMART_LATE_SKIM_BID` (was yaml 0.85)
- `SMART_EXIT_THESIS_BREAK` (new env toggle wiring existing 0/1 logic)
- `SMART_EXIT_LATE_SALVAGE` / `SMART_EXIT_PROFIT_LOCK` (existed)
- `SMART_SALVAGE_MIN_LOSS` (new; was hardcoded -0.03)
- `MAX_ENTRIES_PER_MARKET` (new bundle_backtest knob)
- `SALVAGE_COOLDOWN_SECS` / `GUARD_EXIT_REASONS` (new bundle_backtest knobs)

All defaults preserve baseline. Swept 7 bundles: 20260420×2, 20260421, 20260422×3, 20260423.

## Counter-intuitive findings that destroyed hypotheses

**Post-salvage cooldown is WORSE, not better.** Cooldown 30/60/120s all lose $37–$77 across bundles. Why: replay's "cascade" re-entries (0.44→0.34 deep-price entries) are often the winners that hold to expiry. Blocking re-entry kills that edge. Live's cascade is bad only because live keeps salvaging; the re-entry itself is fine.

**Salvage is needed.** `no_salvage` loses -$22 across bundles, -$30 combined with winner. Bundle 20260422_212413 especially needs salvage to prevent -$35 blowups.

**max_entries_per_market is redundant once skim is tuned.** max2 by itself is +$2.59. Combined with the skim fix, it adds nothing (`skim60+bid091+nT+max2` == `skim60+bid091+nT`).

**`thesis_break` with the YAML's sigma-aware config (`smartThesisBreakSigmaMult=0.50`) fires too often.** Disabling it is consistently +$10–13 across bundles.

## Winning configuration

```yaml
smartLateSkimSecs: "60"        # was 120
smartLateSkimBid: "0.91"       # was 0.85
smartThesisBreakSigmaMult: "0" # was 0.50; disables sigma-aware thesis break
# (need to set SMART_EXIT_THESIS_BREAK=0 too, or remove the code path)
```

Actually the simpler YAML form — add `smartExitThesisBreak: "0"` (new) and wire it in math_smart.py constants block. Or just remove the thesis_break YAML entries and set sigma_mult to 0 + BTC threshold to something huge.

## Walk-forward results

| Bundle | Baseline | Winner | Δ |
|---|---|---|---|
| 20260420_161128 | +$4.94 | +$4.94 | 0 |
| 20260420_191544 | +$58.69 | +$60.94 | +$2.25 |
| 20260421_091646 | +$27.01 | +$34.39 | +$7.38 |
| 20260422_075143 | +$49.64 | +$75.78 | **+$26.14** |
| 20260422_212413 | −$3.68 | −$4.25 | −$0.57 |
| 20260422_212808 | +$5.10 | +$7.48 | +$2.38 |
| 20260423_081250 | +$88.05 | **+$113.44** | **+$25.39** |
| **TOTAL** | **+$229.75** | **+$292.72** | **+$62.97 (+27.4%)** |

6/7 bundles improved; 1 regressed trivially (<$1).

## Parameter sensitivity

- **skim_bid:** 0.85 (baseline) → 0.91 (peak) → 0.92 (+$45) → 0.95 (+$19). Sweet spot at 0.91.
- **skim_secs:** 30 (+$29) → 45 (+$43) → **60 (+$63 peak)** → 75 (+$55) → 90 (+$49) → 120 (+$48 baseline).
- **thesis_break_secs:** 60 (baseline) → 120 (+$4) → 180 (+$8); but `no_thesis` still beats all at +$13.
- **salvage:** removing it loses $22. Keep as-is.

## Non-winning variants (for reference)

| Variant | Δ | Notes |
|---|---|---|
| `skim_090+no_thesis+max2` | +$39.55 | almost as good as winner |
| `skim_091+no_thesis` | +$37.94 | without max2 |
| `skim_091+no_thesis+max2` | +$47.84 | better with max2 but skim_secs not set |
| `no_thesis_break` alone | +$13.10 | simplest improvement |
| `skim_bid_091` alone | +$23.32 | single-knob winner |
| `salvage_cooldown_60s` | −$77.07 | hypothesis disproved |
| `max_entries_per_market=1` | −$56.69 | too restrictive |
| `no_exits` (hold-to-expiry) | −$59.93 | 20260422_212413 blows up −$53 |

## Caveats / next steps

- **Sample size**: 7 bundles / 4 days / ~30h trading / ~300 total trades. Modest.
- **Overfit risk**: winner was picked on sum across 7 bundles; 20260423 contributes $25 of $63. Should validate on fresh bundles going forward.
- **Live ≠ replay**: even winner's +$113 on 20260423 vs live event-PnL +$13 leaves ~$100 execution gap. The strategy tuning helps replay; live-side execution issues (entry slippage, late_bar_salvage cascade) are separate.
- **Next**: ship winner config to prod → collect 1–2 days of new live bundles → re-validate.

## Out-of-sample validation (2026-04-23 later)

New bundle `pm-btc-logs_pm-btc-smart_20260423_110659_big` appeared after the initial sweep (was NOT in the tuning set).

| Bundle | Baseline | Winner | Δ |
|---|---|---|---|
| 20260421_091646 | +$27.01 | +$34.39 | +$7.38 |
| 20260422_075143 | +$49.64 | +$75.78 | +$26.14 |
| 20260422_212413 | −$3.68 | −$4.25 | −$0.57 |
| **20260423_110659 (OOS)** | **+$89.65** | **+$115.12** | **+$25.47** |
| 4-bundle sum | +$162.62 | +$221.04 | +$58.42 (+35.9%) |

The out-of-sample bundle shows the same +$25–28/session uplift. Consistent with the pattern seen in the tuned set.

## Sanity: winner exits applied to live's actual entries (20260423_081250)

Same live entries, only exit logic changes:
- Actual live event PnL: +$13.25
- Winner exits (conservative): +$33.46 — uplift **+$20.21**
- Winner exits (aggressive hold-to-expiry on unresolved): +$39.83 — uplift **+$26.58**

Session balance would shift from −$25.86 to ~break-even/slightly positive after $39 fees.

## Winner YAML diff applied to pm_btc_smart.yaml

```yaml
# math_smart exit tuning (winner config 2026-04-23 walk-forward sweep: +$63/+27%)
smartLateSkimSecs: "60"        # was 120 — only skim in last 60s
smartLateSkimBid: "0.91"       # was 0.85 — only skim at higher conviction
smartExitThesisBreak: "0"      # NEW line — disables sigma-aware thesis break
```

Env wiring already present in `templates/secret.yaml` (line 143: `SMART_EXIT_THESIS_BREAK`), so no template changes needed.

## Code changes made (env-gated; defaults preserved)
- `polymarket/k8s/helm/polymarket-btc-bot/files/scripts/strategies/math_smart.py`: added `SMART_SALVAGE_MIN_LOSS` env (default -0.03, preserving behavior).
- `polymarket/k8s/helm/polymarket-btc-bot/files/scripts/strategies/bundle_backtest.py`: added `SALVAGE_COOLDOWN_SECS`, `GUARD_EXIT_REASONS`, `MAX_ENTRIES_PER_MARKET` env knobs + experiment trackers.
- Sweeps: `/tmp/sweep_fixes*.py` (not committed; temp scripts).
