# settlement-sniper

Standalone bot that captures the **post-close settlement-snipe edge** on Polymarket
UpDown 5m crypto markets: once a bar closes the winner is *locked* (spot vs open),
but stale ≤5¢ SELL orders on the winning token linger uncancelled during the
resolution delay. Buying them settles at $1 (20×+), near-riskless. This is what the
consistent 5m leaderboard earners do (measured: 75% of their cheap-winner buys are
at 1¢, median +4s post-close).

## Design (why GTC-rest, not a FAK race)
The winners are fast **takers** lifting resting 1¢ sells. We can't win that
sub-second race: EIP-712 signing is ~100–300ms CPU and the CLOB is behind
Cloudflare ~105ms RTT from our node → ~330ms/order. So instead we place **one
presigned GTC bid at the cap on the locked winner** right at close. On placement it
crosses (as a taker) any already-resting sells ≤cap *at their price* (same cheap
fill the fleet gets), and it **rests** to catch later dumps server-side with zero
per-order latency. Unfilled remainder is cancelled at the window end.

`snipe.py` is the whole strategy; all plumbing is the **common module**
(`pm-common/execution`: `TakerRunner` + `FastExec`) plus the shared feeds/CLOB from
every-tick-single, wired via `src/` symlinks. The runner's post-close grace
(`POST_CLOSE_GRACE_SECS`) lives in the shared `pm-common/execution/runner.py`
(gated, default 0 = no effect on other bots) with the setter in `core/pm_ws.py`.

## Layout
```
settlement-sniper/
  src/
    snipe.py                                   # the strategy (real file)
    execution -> ../../pm-common/execution     # COMMON module (runner, fastclient, tickbus, events)
    core      -> ../../every-tick-single/src/core     # feeds (binance_ws, pm_ws, gamma)
    engine    -> ../../every-tick-single/src/engine   # clob signing/posting
    config.py -> ../../every-tick-single/src/config.py
  chart/            # self-contained helm chart (own templates/values/bots)
    bots/{btc,eth}_snipe.yaml
  deploy.sh         # rsync -aL src → chart/files/scripts, then helm upgrade
```

## Deploy
Always `source ../.dev-env-source` first (Hetzner k3s, ns `every-tick-single`).
```
./deploy.sh btc paper     # paper (no creds)
./deploy.sh btc live      # LIVE — real orders, $5/deal, $20/day cap (layers creds overlay)
```
Live wallet is the shared `every-tick-single/chart/bots/pm.secret.yaml` (0xD632…).

## Key params (chart/bots/*.yaml → SNIPE_* env)
- `snipeCap` 0.05 — bid/limit price (buy winner at ≤5¢)
- `snipeFireMaxSecs` 7 — post-close window we hold the resting bid
- `snipeNotional` 5 — $/bar
- `snipeMinLeadBps` 1 — skip near-tie bars (ambiguous winner)
- `snipeMaxDailyLoss` 20 — realized-loss halt (settlement-lagged; real cap ~$25–30)
- `postCloseGraceSecs` 10 — runner keeps the closing market live this long past bar-end
- `favOrderType` gtc — REQUIRED (fak would kill the remainder instead of resting)

## Events (logs-training-events.jsonl)
`SNIPE_LOCK` (winner locked) → `SNIPE_REST` (bid placed; imm_fill/imm_px = taker
cross on placement) → `SNIPE_FILL` (filled/fill_px/taker_cross/rested_fill) or
`SNIPE_NOFILL` → `SNIPE_SETTLE` (real PnL) / `SNIPE_HALT`.
