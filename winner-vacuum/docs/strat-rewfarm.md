# strat-rewfarm — liquidity-rewards farming on the Aug-2026 $1M program

Created 2026-08-17 (session: maker-bot revival). Status: **SHELVED by user
2026-08-18 ~12:15 Kyiv** — go-live declined; paper pods btc/xrp REMOVED in
the "vac fleet only" cleanup (17 trader releases uninstalled). The research
below stands; mrec4h recorders keep collecting, so the 4h thesis can be
re-validated offline and revived any time before the program ends Aug 31
(deploy yamls remain in chart/bots/*_rewfarm4h.yaml).

## 1. The program (verified via CLOB API + docs, 2026-08-17)

$1M through August on crypto TWAP updown series ONLY (5m/15m/4h). Daily
pools (`rate_per_day`, USDC, paid 00:00 UTC, min payout $1):

| series | btc | sol/eth/hype/xrp | bnb/doge |
|---|---|---|---|
| 5m | $10,000 | $1,666.67 | $833.33 |
| 15m | $7,500 | $833.33 | $416.67 |
| 4h | $1,666.67 | $333.33 | $166.67 |

Mechanics (docs/programs/liquidity-rewards + live poller, all verified):
- Band **v=1.5¢** of the size-cutoff-adjusted midpoint, **min order 50sh**,
  weight `((v−s)/v)²·size`, sampled ~1/min (random), pro-rata across makers
  by `Q_min` (two-sided min; single-sided ÷3 while mid∈[0.10,0.90], zero
  outside). BUY-UP + BUY-DOWN counts as two-sided (bid m scores side 1,
  bid m' scores side 2).
- **Only the CURRENT bar-market carries the rate** (rotation poller
  2026-08-17 ~23:15: next-bar configs = NOROWS the whole bar). Pre-open
  quoting earns NOTHING (a measured 76% pre-open share is worth $0).
- **Config attaches ~50s AFTER bar open** → the first minute never scores.
- Tick geometry: with 1¢ ticks, only levels ≤1.5¢ from mid can score ⇒
  only the touch levels (spread ≤2¢) or one improving level. Top-of-book
  data fully determines the field's Q — mrec suffices for offline sims.
- Maker rebate (separate program): crypto = 20% of taker fees per market,
  fee-curve weighted ⇒ ≈ `0.2·0.07·p(1−p)` per filled maker share
  (~0.35¢/sh at p=0.5). Paid daily, $1 min.

## 2. What was measured (rewsim3, local mrec archive, delay 0.4s, QH both)

Two-sided 50sh/side quoting 0.5¢ inside the band, per-side 1-fill cap,
pair ceiling 0.985, stand-down 45s(5m)/75s(15m), warmup, config-lag
honored. 7 coins × 7 days 5m + btc/eth 15m × 5 days. Policies: base1
(no gates), guard (loser-kill |lead|≥6 + signed velocity kill), pairfav
(post-pair favorite re-arm), favonly (signal side only).

**5m: NET −$300…−$1,000/day per coin, every policy, every coin.**
Decomposition (typical, xrp): pairs +$580/d (median pair 0.98 — the
ceiling works), rewards $60-130/d, rebates ~$85/d, **singles −$1,300/d**
(win 17-29%, ≈ −$21 per single 50sh). btc's $10k pool yields only
~$29/d captured — the field is thick and presence stops at the first
pair. Key diagnostics:
- **Velocity gating cannot dodge the toxic fill**: 43 of 48 loser-singles
  filled at FLAT lead velocity (±1.5bps/1.5s window). The sweep and the
  spot move are simultaneous at 100ms resolution. (ONE WALL, again.)
- **favonly refutes favorite-dip buying mid-bar**: 507 fills, 63% win,
  −6.2¢/sh — |lead|≥1bps is already in the mid price. (The vacmaker
  92-97% accuracy lives at T≤30s / 0.97+ prices, not mid-bar.)
- **Queue position filters out the GOOD fills**: strict-queue world was
  MORE negative than optimistic (−1356 vs −742 xrp) — pair completions
  wait in the FIFO and die; toxic through-sweeps bypass the queue.
- Re-arm after pairs (pairfav/v2 MAX_PAIRS=3) is toxic: pairs 230→496 but
  singles 80→191; second rounds harvest fresh losers.

**15m: btc ≈ −$205/d, eth ≈ −$130/d** (base1/guard, 5 days). 3-4× better
than 5m (oscillation), still negative; reward capture collapses to
$0-28/d (presence dies at the first pair; field thick on btc).
Single-day favonly outliers (+$513 btc 08-16 vs −$1,274 08-14) are
directional luck, not edge.

**Duration ladder is mechanistic**: completion at touch 5m 63% → 15m
~72% → 1h 84% (live-proven +$1/bar) → 4h expected best. The single-leg
toll shrinks with bar length; the reward pool does not.

## 3. The surviving thesis: 4h reward-farm (pilot)

- 4h in-band field is nearly EMPTY (live snapshots 22:58 + 23:30 Kyiv):
  btc Qw 947/23 (bid touch 47sh — below the 50sh cutoff, scores zero),
  eth 12/36, xrp 5/5, sol 9/5, doge 11/9, bnb/hype literally 0.
  A 50sh two-sided join at 0.5¢ inside (Q≈22/side) ⇒ ~50-77% share of
  alt pools (**$150-250/d per alt**), ~5-15% of btc (**$100-250/d**).
- Flow is light (btc 4h: 727sh in first 32min) → few fills; 4h
  oscillation completes pairs (1h mechanism, more so).
- Economics at 50sh: capital ~$50/coin locked, worst case capped by
  PAIR_CEIL + per-side cap + $12/day halt.
- Risks: (a) competitors arrive (pools are public; program ends Aug 31 —
  first-mover window is NOW); (b) thin-book pickoffs on stale mids —
  mitigated by slow-chase re-centering + never-above-mid guard + halts;
  4h btc/eth books have real MMs keeping mids honest; (c) the last-hour
  decided phase — MID band [0.12,0.88] + QUIT_TL 900 stand it down.

**Deployed 2026-08-17 23:33 Kyiv (PAPER)**: `btc-rewfarm4h`,
`xrp-rewfarm4h` — poolfarm.py UNCHANGED (battle-tested: pair ceiling,
hard per-side caps, sticky halt, hold-to-redemption, resolve loop) +
new chart env (`pmMmNoChase=false`, `pmMmPairCeil`, `pmMmVolPullC`
added to secret.yaml). Config: EDGE_C=0.5¢ (w=0.44 — the old 1.5¢
far-edge quoting scored ~0 and was why poolfarm earned only $4.67/day),
RECENTER 1¢, MIN_REST 8s, QUIT_TL 900, WARMUP 90, size 50, halt $12.
First quotes verified: btc 4h book 0.56/0.57 → BUY UP 0.56 + BUY DOWN
0.43, both w≈0.44. Deploy: `./deploy.sh <coin> paper|live rewfarm4h`.

## 4. Open items / v2
- **Empty-book coins (hype/bnb/doge 4h, ~$666/d unclaimed)** need
  four-sided quoting to CREATE a scoreable mid: mint 50U+50D via
  CtfCollateralAdapter (mintsalvage plumbing) + bid/ask both tokens
  around a spot-anchored model fair. ~$100 capital per coin. Not built.
- 15m btc "contested-open window" (first minutes, mid≈0.5): unmeasured
  as a standalone window; likely marginal after config-lag.
- Live share verification: GET /rewards/user/percentages (L2 auth) from
  a pod once live; also next-day earnings via /rewards/user.
- mrec4h recorders (btc/eth/sol/xrp/hype) deployed 23:27 Kyiv — the 4h
  ground-truth dataset accumulates from now; re-run rewsim3 on it after
  a few days to validate the 4h fill model against paper/live.
- 5m/15m: do NOT re-enter in-band. Third confirmation, now WITH rewards.

---

## POST-MORTEM 2026-09-02 — the August program is OVER, verified on-venue

Checked `docs.polymarket.com/market-data/market-details.md#liquidity-reward-settings`
against live gamma. Two separate maker subsidies, do not conflate them:

**1. Liquidity rewards (`clobRewards`) — ⛔ ZERO on every crypto up-down market.**
Read `rewardsMinSize` / `rewardsMaxSpread` / `clobRewards[].rewardsDailyRate` off gamma.
As of 09-02, btc/eth/sol/doge/xrp × {5m, 15m, 4h} all return **no `clobRewards` array at all**
⇒ dailyRate 0. The field is NOT simply omitted by the endpoint — 136 of the top 500 active
markets by 24h volume DO carry it (Fed markets $1,000/day, tennis $0.001/day), so absence
is real. The $1M August program ended 08-31 exactly as scheduled. **This kills the 4h rewfarm
thesis** (it was priced entirely off alt pools of $150-250/day). Re-check before any revival:
one gamma call per slug, look for a non-empty `clobRewards`.

⚠️ `rewardsMinSize` is 50sh but **`rewardsMaxSpread` is per-BAR, not a constant 1.5¢** —
observed 0 / 1.5 / 4.5 / 4.5 across four consecutive btc 5m bars, and 1.5 vs 4.5 differing
across coins in the same bar. Our "1.5¢ band" note was an observation of one config, not a rule.
Never hardcode it; read it per market.

**2. Maker rebate (`feeSchedule.rebateRate`) — 🟢 LIVE and unchanged.**
Live on all 5m crypto: `{rate: 0.07, exponent: 1, takerOnly: true, rebateRate: 0.2}`,
`feesEnabled: true`. Confirms the fee shape `shares × rate × p^e × (1−p)^e` and that
**`makerBaseFee`/`takerBaseFee` = 1000 are legacy nominal fields — ignore them**, the
`feeSchedule` object is the truth.

⭐ OPEN LEAD (not yet sized): makers are paid **20% of the taker fees** collected in the
market, daily, pro-rata. On 5m crypto a taker at 50¢ pays 3.5% of notional, so the rebate
pool is 0.7% of taker notional — an order of magnitude the old rewards program never reached
per-dollar. Sylldra (0xfd9b7636) collects ~$1.0-1.6/day of it on ~$100-200/day of maker
volume. Sizing this pool is the unanswered [[openmm-5m-maker]] rebate question and is now
answerable from `MAKER_REBATE` activity rows + venue taker volume.
