# Intra-bar trading investigation — 2026-07-13 overnight

Goal: find how to trade INSIDE the 5m candle (beyond the 50c cur2 bettor), using
Binance data, our 10.3M-event CLOB snapshot dumps, and 8 leaderboard wallets.
Four parallel agents + local synthesis. Artifacts in the session scratchpad
(`leaderboard/`, `snapshot-backtest/`, `binance-calib/`, `paper-analysis/`).

## 1. What the 8 leaderboard winners actually do

All 8 profitable wallets trade the same 5m UpDown markets. Fingerprints
(data-api activity, 34h deep window + user-pnl API):

| wallet | $/day | green days | mechanics |
|---|---|---|---|
| hot-garbage | 1,360 | 40% | 24k fills/34h, BUY-only, **88.8% of bars BOTH sides**, median clip $2.85, entry p50 0.45 |
| antsaslyku | 1,501 | 81% | BUY-only, 59% both sides, entry p50 0.54 |
| xd4253… | 641 | 52% | eth-only, **97.2% both sides**, entry p50 0.40 |
| tuuutaaaaata4 | 180 | 20% | eth-only, 96.6% both sides |
| vitozhang | 368 | 76% | eth-only, 75.8% both sides, entry p50 0.28 |
| neversmiling | 1,219 | 68% | 76.6% both sides, entry p50 0.39 |
| ohioriskmanagement | 674 | 60% | 66.7% both sides, entry p50 0.40 |
| unnamed 0xe3ee… | 1,100 | 57% | the one TAKER-style outlier: p50 0.04 tail buys + mid-bar sells, dd $27.5k — lottery profile |

**Archetype: two-sided model-priced accumulation, all bar long (entries spread
20s–270s into the bar), thousands of tiny clips, zero sells, hold to resolve.**
The tiny clip sizes + both-sides + spread-out timing = resting MAKER ladders
being filled by panicking takers — **makers pay no fee on these markets**
(taker_base_fee=1000bps, fee = 0.10·p·(1−p)/share; makers 0).

## 2. Favorite-taker (fav_taker) verdict — marginal, fee-bound

- 33h live-paper (5 coins): +$114, 92.2% win @ 0.894 avg entry = +2.7c/share
  gross, **but fee-free accounting**; fee ≈ 0.95c/share → ~+1.8c net. Entries
  >0.94 breakeven; 0.80–0.85 miscalibrated (won 84% vs model 92%).
- Replay on the 7-day snapshot dumps (REAL recorded asks, TRUE gamma labels):
  gross EV only +0.5–1.3%/bet, xrp negative, btc decays train→test; **every
  variant net-NEGATIVE after fees OOS** (−0.8 to −1.5%/bet), including with the
  corrected model. 1,152-config grid search finds nothing robust.
- Probes: persistence gate = overfit; early entry (0.70–0.85) = dead;
  ask already repriced at model-cross in ~80% of bars (lag p50 12–16s when it
  exists); btcagg aggregate feed adds nothing.
- Binance 1s calibration (30d, 2.37M rows): Phi(z) fat-tailed (t df≈3); **BTC
  overconfident −2.2…−2.6pp in the firing zone** (fix: z/k, k=1.24@15-60s);
  knife-edge bars (|final lead|<2bps) win only 62.6% → 4bps fire floor;
  violent last-30s aligned moves win 90.4% vs 92.7% → momentum brake.

**Conclusion: taking the favorite at the ask pays the 10% fee formula + adverse
selection for a ~1% gross edge — structurally marginal. The steady leaderboard
money is on the MAKER side of exactly these flows.**

## 3. What's now deployed (ns `every-tick-single`)

1. **fav fleet upgraded** (fee-aware net-edge gate, entry cap 0.94, min |lead|
   4bps, BTC z-shrink): eth/sol/xrp/doge PAPER; **btc-fav LIVE** ($5 orders,
   $10 daily loss cap, no cur2 conflict on btc) — purpose: measure REAL fill
   quality/slippage vs paper assumption, the one thing no backtest answers.
2. **NEW `<coin>-lock` fleet (btc/eth/sol/xrp/doge, PAPER)** — the leaderboard
   archetype: `maker_rebate` strategy `QUOTE_MODE=model`: rest BUYs on BOTH
   sides at `fair_p(side) − 0.04`, floor 0.05 / ceil 0.90, pair budget ≤0.94,
   reprice on drift/z, 30 shares/side cap, warmup 15s, cutoff 30s, fills on
   real trade prints (paper_book), hold to expiry, maker fee 0.
   Success gate: paper EV/bar > 0 with realistic (trade-print) fills over ≥3
   days; then live with small caps.

## 4. Results so far (updated 2026-07-14)

- **btc-fav live test (07-13, 7 bets, ≈−$5 net)**: FAK fills matched or beat
  the quoted ask → execution risk retired; paper fills are trustworthy. Back
  to PAPER; future live only on a separate account.
- **fav fleet paper, 21h, 410 bets net of modeled fees: −$19.25** (btc +0.9,
  eth −35.2, sol −1.5, xrp −6.7, doge +26.3). Loss concentrated in EARLY
  entries: t_left 120–300s = −$29.2 (avg −13c/bet) while t_left <60s = +$13.9
  (avg +17c/bet); price 0.78–0.86 avg −11.8c vs 0.86–0.95 avg −2.5c.
- **lock v1 (55 bars)**: locked pairs +$185, one-sided directional −$697 →
  v2 same day (momentum brake >1.3σ, +4c against-momentum margin,
  pair-completion chase, 5-share clips).
- **lock v2, 16h, ~200 bars/coin**: locked +$322, directional −$328, gross
  ≈ −$6 pooled (vs v1 pace ≈ −$1.9/bar → now ~breakeven). Both-sides
  completion still only 10–22% vs hot-garbage's 89% — the remaining gap.
  xrp worst (10% completion, −$204). Gate to live unchanged: EV/bar > 0 over
  ≥3 days + completion materially up.

## 5. Deployed 2026-07-14 (all PAPER)

1. **fav fleet pocket gates** (`FAV_POCKETS` JSON env): only fire in the two
   pockets that were net-positive on the 7d truth-labeled backtest —
   `0.78–0.90 @ t_left 10–120s, net edge ≥3c` and `0.62–0.78 @ 10–60s, ≥4c`.
   Kills the 120–300s early entries that produced the whole 21h loss.
2. **NEW `<coin>-mom` fleet (sol/btc/xrp)** — antsaslyku archetype (the only
   leaderboard TAKER measured positive in every bucket, +3.1–5.4%/bet): buy
   favorite at 0.50–0.70 with 60–270s left, only when the 30s Binance move is
   momentum-aligned 0.2–1.3σ (mom=1 pocket). No PVCs (node volume limit).

## 6. 15m / hourly market scoping (2026-07-14)

- Slugs: `<coin>-updown-15m-<unix>` (900s-aligned) and
  `<fullname>-up-or-down-<month>-<day>-<year>-<Ham>-et` (hourly).
  neversmiling runs 5m/15m/hourly ≈ 56/17/27% of trades; unnamed ≈ 18/50/32%
  (15m is unnamed's MAIN venue).
- **Identical microstructure**: taker_base_fee 1000 bps (same p(1−p) fee),
  maker free in practice, 1c tick, $5 min order → all strategies port as-is;
  only BAR_SECONDS + slug pattern change.
- Liquidity per market: 15m vol $0.3–9k, top-5 depth $180–600/side (≈ 5m);
  hourly vol $0.3–10k, spreads widen late in the hour. Fewer bars/day
  (96 vs 288) but 3× more time per bar for two-sided accumulation — likely
  HIGHER pair-completion for the lock strategy, and less bot competition
  than 5m. → Best candidate: port lock to 15m once lock v2 5m data is read.

## 7. Next steps

- 24h read on pocket-gated fav (bets/day will drop sharply — intended) and
  mom fleet first EV numbers.
- Lock v2: 3-day EV/bar + completion verdict → live candidate on separate
  account; if completion stays <30%, port lock to 15m markets first.
- xrp-lock: investigate the −$204 directional bleed (worst completion).
