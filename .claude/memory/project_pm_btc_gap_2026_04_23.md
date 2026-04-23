---
name: PM BTC smart — replay-vs-live gap analysis (2026-04-23 bundle)
description: Bundle pm-btc-logs_pm-btc-smart_20260423_081250 (10.7h, 94 live trades). Decomposes why live underperformed replay by $114 on $100 notional.
type: project
---

## Bundle
`polymarket/k8s/helm/polymarket-btc-bot/pm-btc-logs_pm-btc-smart_20260423_081250`
2026-04-22 18:25 → 2026-04-23 ~02:29 UTC (10.7h, 94 trades, WR 60%)

## Headline numbers

| | Replay | Live event-PnL | Live balance Δ |
|---|---|---|---|
| PnL | **+$88.05** ($100 base) | **+$13.25** (~$55 base) | **−$25.86** ($54.98→$29.12) |

Two independent leaks:

### Leak 1 — Strategy PnL erosion: replay → live events = −$55.03 (93 paired trades)
- avg `live_entry − replay_entry = +1.67¢` (live paid more)
- 46 trades paid >0.5¢ more on entry; only 17 paid less
- 2 direction mismatches (replay DOWN → live UP) due to market drift between decision & fill
- Worst-10 trades have 7–36¢ entry slippage AND sized smaller than replay (e.g. 6:30PM: replay 29 sh → +19.14, live 13 sh → −1.07)

### Leak 2 — Event PnL → balance: −$0.40/trade (52 clean 1-trade intervals)
- mean −$0.40/trade, median −$0.34, range [−$1.01, −$0.17], **never positive**
- by reason: skim −$0.32, salvage −$0.60, force_close −$0.41, thesis_break −$0.42
- fee/share ~2–3¢; looks like fixed gas per fill scaling with share count (Polymarket taker fee + Polygon gas)
- Session aggregate: −$39.11 leak / 94 trades = −$0.42/trade

## Conclusions

1. **Primary bottleneck is execution slippage, not fees** — $55 leak in (1) vs $39 in (2). Reinforces 2026-04-22 execution-fix memo (FAK thin-book, 425 service-not-ready, stale approvals).
2. **Fees are small and consistent** — treat as ~$0.40/trade fixed cost in profitability calcs. Not worth optimizing until (1) is addressed.
3. **late_bar_salvage is doubly bad** — worst edge in replay AND highest per-trade fee; consider disabling or narrowing the trigger.
4. **Replay strategy is fine.** +$88/10.7h = $197/day on $100 notional. Getting live to capture this edge is the optimization target.

## Root-cause drill (top-10 worst-slippage trades)

**Primary cause is strategy behavior, not execution infra.**

### Cascade re-entries are the #1 loss driver
| opens per market | markets | trades | sum PnL | avg/trade |
|---|---|---|---|---|
| 1 | 52 | 52 | +$13.88 | +$0.27 |
| 2 | 16 | 32 | +$15.96 | +$0.50 (works!) |
| 3 | 2 | 6 | **−$8.91** | **−$1.49** |
| 4 | 1 | 4 | **−$7.68** | **−$1.92** |

3 markets with ≥3 re-entries cost **−$16.59** alone. The 6:30PM ET market cascade: buy @0.60→salvage@0.47→buy@0.48→salvage@0.39→buy@0.40→salvage@0.33→buy@0.34→salvage@0.31. Replay held its single 0.34 entry → +$19.14; live salvage-and-rebuy loop → −$7.68.

### Force-close / salvage exits clip winners
Many worst trades had live enter, exit early for small win/loss, while replay held to expiry for big win:
- 2:30PM: live salvaged @0.41 (−$4.39) vs replay held @0.50 → +$10
- 5:20PM: live force-closed @0.67 (+$1.55) vs replay held → +$9.12
- 7:15PM: live skimmed early (+$1.91) vs replay held → +$8.00

### Entry latency (decision→fill)
- avg live_entry − replay_entry = **+1.67¢** (live pays more), 46/91 trades >0.5¢ worse
- 2 direction flips because price moved enough between decision and fill

### Infra is NOT the bottleneck
Loki log scan: **14 FAK no_match retries, 15 HTTP 400 errors, 0 timeouts/425s/nonce errors** over 94 trades. CTF approvals pre-warmed every 5 min on bar boundary (working as designed from 2026-04-22 fix memo).

## Prioritized fixes
1. **Cap re-entries per market at 2** — would eliminate −$16.59 cascade loss on 3-market tail
2. **Tighten late_bar_salvage threshold** — current trigger fires on small drawdowns that would mean-revert; needs wider stop or skip-after-N-salvages rule
3. **Loosen force_close** — don't exit profitable DOWN positions early; let them ride to expiry when price is still right direction
4. **Fix entry latency** secondary — avg 1.67¢ is worth ~$3–5 of the $55 execution gap, not the primary target
