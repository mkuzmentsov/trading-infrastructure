# Tail-strategy backlog & open questions

Live experiment: buy near-dead UpDown tail (best ask 1–8c in the final 5–30s)
when its model-implied value clears a net edge; hold to resolution. Fleet is
paper (6 coins × 5m/15m/1h) + tail-v2 A/B; live btc-tail halted 2026-07-17.

## Standing findings (do not relitigate)
- **$5/bet is the capacity wall.** Marginal $ beyond it lands 16:1 (5m) / 19:1
  (15m) into corpses — winning tails get swept clean, dead ones have deep
  books. Scale = MORE MARKETS, never more $/market. Proven on real ladders.
- **8c sweep cap correct for depth**, BUT 7–8c *entries* lose (see #2). Depth
  grows with price; lowering cap for fills would hurt.
- **Take-profit at any level (0.25–0.50) is WORSE than hold** (real tick paths,
  326 bets): a TP caps 100% of winners (all pass through 40c → +$0.35 vs
  +$0.95) to rescue the ~4% "spike-then-die" losers. Convex lottery — the fat
  right tail IS the edge. Retest at larger n but sign is structural.
- **bookTicker feed = parity** for gate-driven decisions; aggTrade everywhere.
- Paper fills now depth-honest (cumulative ladder sweep ≤ cap); btc live fills
  86–90% vs paper's understated ~55% (btc paper PnL is conservative).

## OPEN — prioritized

### 1. tail-v2 forward A/B (DEPLOYED 2026-07-19, judge ~2 days incl. weekday)
Four gates from the 2251-bet pooled analysis (all IN-SAMPLE except momentum,
which is OOS-consistent w/ 30d calibration — treat as hypotheses, validate
FORWARD vs v1):
- `p_hi 0.06` — 7–8c entries lost −$1130; sweet spot 4–6c (+$1.2–2.0/bet)
- `tl_hi 20` — 25–30s-left fires lost −$982; ≤10s wins 8.8% (+$1.85/bet)
- `true_hi 0.45` — model anti-predictive; >0.5 confidence bucket lost −$347
- `mom_skip 0.0–1.0` — dead zone lost −$772; >1.0σ snap-back +$717 (KEEP)
Metric: EV/bet & win% (v2 fires ~⅓ as often), NOT total PnL.

### 2. MODEL QUALITY — evidence-gated on #1
The diffusion model (Binance lead/√(σ·t_left) → Φ(z)) has ZERO predictive
power for tails: win% flat ~5% across ALL fav_true buckets, no monotonicity.
Not just miscalibrated — BLIND to tail liveness in the endgame. Hypothesis:
tail edge is STRUCTURAL (cheap+late+snap-back), not predictive → model may be
decoration. Candidate rebuilds (do ONLY if v2 fails to beat v1):
- **Chainlink/aggregate-aligned lead** (`PRICE_LEAD_SOURCE=aggregate`) —
  resolution IS Chainlink median; Binance-only diverges exactly at knife-edge.
  Most principled; cheapest as a 3rd A/B arm `tail-agg` NOW (parallel w/ v2).
- sigma floor + isotonic recal — cosmetic (fixes 0.50-stamp/0.99-glitch), won't
  create signal that isn't there. Low priority.

### 3. TIMEFRAME: 15m >> 5m (STRONGEST current signal)
Over the same 3-day weekend: 5m paper ≈ −$500, 15m paper ≈ +$200 (stable
across every check, 5/6 coins green, btc 15m best @ 15% while btc 5m marginal).
Plausible mechanism: 15m bar travels ~3× → final-30s "dead" tails more often
alive. Coin-inversion vs 5m (xrp best@5m/worst@15m). If it holds through a
WEEKDAY, live candidate = btc-15m $5. 1h too slow to judge (~1 fire/coin/day).

### 4. TIME-GATING (weekend/hour) — analyze at Wednesday read
Losing sessions cluster Fri-eve→Sun (weekend = thinner panic flow = fewer
mispriced tails). Cut pooled per-coin EV by day-of-week × UTC-hour; if weekend
cells are the losers, operating rule = run only in profitable window. Turns
"edge is thin" into "edge is time-gated."

### 5. NO stable per-coin edge
Every coin took a turn as hero AND zero over 4 days (doge +$205→−$160,
xrp +$204→−$120, bnb loser→best). Judge POOLED over ≥6 days + multi-regime,
never single-window coin-picking (the reverse-cut would've been wrong).

### 6. GTC / resting remainder (data preserved, sol GTC ran 2026-07-16)
Only mechanism that could invert corpse-depth adverse selection: a resting bid
fills on dumps sweeping THROUGH price (flow) not standing depth (stock).
`FAV_ORDER_TYPE=gtc` built. Revisit for thin coins after v2/timeframe verdicts.

### 7. Live restart decision (btc-5m halted; wallet $297.93 topped up)
btc live-fill advantage (86–90% vs paper 55%) means real btc EV > paper. But
5m marginal & weekend-negative. Gate live restart on: v2 or 15m proving out +
weekday regime. Live caps back ON ($10–15/day, never 99999). Separate account
someday.

### 8. Ops: feed-staleness watchdog (queued)
RTDS silent-death killed 3 makers for 28h (fresh=False, zero quotes). Makers
gone now, but any tail bot's Binance feed going stale would silently stop fires
& skew samples. Add: flag/self-restart a bot whose reference feed age > ~10min.

## Non-starters (closed)
Kalshi (Ukraine restricted); US/Germany nodes (geo-blocked); order ladder /
price-chasing / cap-raise to 10c (all lose on data); no coins beyond the 6
(full universe); dip/fav/mom/lock fleets destroyed 2026-07-17.
