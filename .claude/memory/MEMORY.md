# hummingbot-infra Project Memory

## Project Overview
Infrastructure-as-code for deploying crypto trading bots (Hummingbot + Freqtrade) on Hyperliquid exchange. Uses Ansible for VM provisioning and Kubernetes/Helm for container deployments.

- **Root:** `/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra`
- **Main branch:** `main`, **Dev branch:** `develop`
- **Target OS:** Ubuntu 24.04

## Top-Level Structure
```
hummingbot/     # Ansible playbook - unified Hummingbot stack (API, Dashboard, Gateway, EMQX, Redis, Postgres)
                # Also: hummingbot/k8s/ - K8s Helm chart for HL-WhiteBIT arbitrage bot
freqtrade/      # Ansible playbook + K8s Helm charts for Freqtrade copy-trading bots
hetzner-k3s/    # Hetzner Cloud K3s cluster config
util/           # Python utilities (hl_leaderboard.py - Hyperliquid leaderboard scanner)
.claude/memory/ # Claude AI session notes (this directory)
```

## Key Details
- See `freqtrade.md` for Freqtrade-specific strategies and deployment
- See `hummingbot.md` for Hummingbot stack + arbitrage bot details
- See `kubernetes.md` for K8s/Helm/Hetzner details

## Active PnL Investigation Notes
- [PM BTC gap 2026-04-23](project_pm_btc_gap_2026_04_23.md) — pm-btc-smart 10.7h: replay +$88 / live-events +$13 / balance −$26. $55 execution-slippage leak + $39 fixed-fee leak ($0.40/trade). Main target: entry slippage.
- [PM BTC tuning winner 2026-04-23](project_pm_btc_tuning_2026_04_23.md) — walk-forward sweep: `skim_secs=60, skim_bid=0.91, thesis_break=OFF` adds +27% replay PnL across 7 bundles (+$63). Counter-intuitive: salvage cooldowns HURT (cascade re-entries are profitable in replay).
- [PM BTC re-entry guard 2026-04-23](project_pm_btc_reentry_2026_04_23.md) — `blockReentryIfBidDropGt: 0.10` adds another +$16.52/+6.6% across 5 bundles. Surgical: only blocks re-entry when same-direction bid collapsed >10¢ since prior exit. Wired into config.py + main.py + secret.yaml + pm_btc_smart.yaml — DEPLOYMENT READY.
- [PM BTC 1h skim sweep null result 2026-05-07](project_pm_btc_1h_skim_sweep_2026_05_07.md) — 26-cell sweep over 5 bundles: production `(SECS=1080, BID=0.99)` is the global maximum (+$195.96). Loosening BID monotonically hurts: 0.99→0.95 −$37, →0.90 −$69, →0.88 −$84. Trade-3 disaster (UP 0.70→0.86→0) needs entry-quality / peak-flat lever, not skim retune.
- [PM maker-rebate roadmap (parked) 2026-05-08](project_pm_roadmap_maker_rebates_2026_05_08.md) — PM pays 20% of taker fees as maker rebate on crypto markets, but `p(1−p)` weighting makes 0.99 exits earn rounding error (<$0.005/trade). Real opportunity is mid-price market making — deferred unless we build a dedicated strategy.
- [PM BTC 1h min-elapsed gate sweep + reject 2026-05-08](project_pm_btc_1h_min_elapsed_2026_05_08.md) — 100-cell sweep over 187h tested CEIL ∈ {0.62-0.70} × MIN_ELAPSED ∈ {0-1200}. Both rejected. Prod (0.70, 0) had best abs PnL (+$213.68). 19.9h "entries ≥0.66 lose" pattern was artifact, not structural. MIN_ELAPSED=600 was briefly shipped and rolled back — ROI +3.4pts but abs PnL −$4 didn't justify the trade.
- [PM BTC 1h structural bleed 2026-05-08](project_pm_btc_1h_structural_bleed_2026_05_08.md) — live corpus PnL is −$363 (271 trades, 47% WR). Bot wins 55% but loses 2.6× per loss vs per win → needs 72% WR to break even. Worst 30 trades (15%) explain the entire loss; other 167 are break-even. No knob retune fixes this; only blocking the worst-30 catastrophes at entry time can.
- [PM BTC 1h fat-tail model overconfidence 2026-05-08](project_pm_btc_1h_fat_tail_model_2026_05_08.md) — math model is 30-45 pp overconfident at p_up extremes (95% of trades). Real moves on losers are 3-4× implied σ. The Gaussian assumption in `_norm_cdf` is the structural cause of bleed. Tighter knobs around a broken model are second-order; first-order fix is calibration.
- [PM BTC 1h killer quadrant (entry × sigma) 2026-05-08](project_pm_btc_1h_killer_quadrant_2026_05_08.md) — 93 trades where entry≥0.66 AND sigma_5m≥0.0006 explain 59% of corpus loss (−$170 of −$286). Cleanest fingerprint identified. Naive `block sigma_5m > 0.0008` saves +$136. Sweep showed +$48 on 5-bundle corpus but **NOT shipped** — failed on 27h and 76.2h bundles (see below).
- [PM BTC 1h SMART_MAX_SIGMA rejected 2026-05-10](project_pm_btc_1h_max_sigma_ship_2026_05_08.md) — **NOT shipped.** 7-cell sweep on 5-bundle corpus: +$48 (+28%). But 76.2h bundle (20260507_091151) replay shows −$21.89 regression (blocks 3 profitable late_bar_skim winners). Two consecutive bundle regressions (27h −$18, 76.2h −$22). Gate shelved — works on old corpus regime, fails on recent regime.
- [PM BTC 1h trade-23 peak-flat failure 2026-05-08](project_pm_btc_1h_trade23_peakflat_2026_05_08.md) — Trade 23 (May 8 3AM ET DOWN @ 0.67 → 0.04, −$21.43) blocked salvage_floor because peak_bid (0.89) − entry (0.67) = 0.22 > peak_flat_max=0.05. Replay confirms structural −$19.80 loss under all configs. Don't try to fix mid-bar; attack the entry side instead.
- [PM BTC 1h rejected hypotheses 2026-05-08](project_pm_btc_1h_rejected_hypotheses_2026_05_08.md) — index of rejected ideas: chop_ratio_30m gate (CHOP 3-5 was actually a winner), entry-band sweep (15 cells, prod wins again), Kelly amplification (cap binds for all trades), hour-of-day filter (noisy, n too small per window). Don't re-litigate without new data.
- [PM BTC 1h bundle 20260507_091151_76.2h](project_pm_btc_1h_profitability_plan_2026_05_10.md) — 76.2h bundle: live −$43.60 (77 trades, 46.8% WR), replay prod −$49.19, replay MAX_SIGMA=0.0010 −$71.08. Live/replay gap only +$5.59 (good alignment). Gates save +$45.84 vs gates_off by converting late_bar_salvage blowouts into earlier thesis_break cuts. Second half of bundle very rough.
- [PM BTC 1h profitability plan 2026-05-10](project_pm_btc_1h_profitability_plan_2026_05_10.md) — 4-phase plan: (1) sweep SMART_SHRINKAGE {0.70-0.92} + SMART_PUP_Z_CAP {1.0-2.0} on 6 bundles — first direct calibration fix; (2) peak_flat_max 0.05→0.30 sweep + drawdown-from-peak gate; (3) empirical WR calibration replacing Gaussian _norm_cdf; (4) strategic pivots (higher min-Z, cheap-side entries). Execution order listed in file.
- [PM BTC 1h calibration sweep 2026-05-10 — SHIPPED](project_pm_btc_1h_calibration_sweep_2026_05_10.md) — Swept SHRINKAGE×ZCAP (125 runs), peak_flat (25 runs), min_z (35 runs), stacked combos. **Shipped: `smartShrinkage=0.80` + `smartSalvageRequirePeakFlatMax=0.20`**. Joint PnL +$138→+$229 (+65%), wins all 5 bundles. ZCAP useless (wrong abstraction). min_z raises hurt absolute PnL. Empirical calibration: p_up≥0.95 trades have 82.9% WR (profitable), bulk [0.92-0.95) at 61.6% is the bleed source.

## Critical Gitignored Files (must create manually)
- `hummingbot/inventory.ini` - Ansible inventory
- `hummingbot/env.values.yml` - Hummingbot configuration values
- `freqtrade/inventory.ini` - Ansible inventory
- `freqtrade/env.values.yml` - Freqtrade bots configuration
- `hetzner-k3s/kubeconfig` - K3s cluster kubeconfig
- `freqtrade/k8s/helm/bots/*.yaml` - Freqtrade bot credentials (use .example as template)
- `hummingbot/k8s/helm/bots/*.yaml` - Arbitrage bot credentials (use .example as template)

## User Preferences
- Always save knowledge to memory inside the project at `.claude/memory/`
- Prefer K8s/Helm for new bot deployments (mirrors freqtrade pattern)
- K8s namespaces: `freqtrade` for Freqtrade bots, `hummingbot` for Hummingbot bots
