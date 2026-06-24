# funding-carry bot

Delta-neutral funding carry: **long Kraken spot + short Hyperliquid perp**, hold
for HL's hourly funding. Backtests (`../backtest.py`, `../backtest_v2.py`) say
*"hold, don't time"* — ~8%/yr on BTC+ETH, ~10–12% with HYPE/LINK added, sub-1%
drawdown in the 2025–26 regime. So the bot just opens the basket and holds, with:

- **regime-flip protection** — close a leg if its funding has been ≤ `funding_exit_apr`
  for `funding_exit_persist_hours`; re-open when smoothed funding recovers.
- **deleverage-on-stress** — if the HL short's liquidation price gets within
  `deleverage_liq_room` of mark, cut the position (and the matching spot); below
  `emergency_liq_room`, close the leg entirely.
- **delta-drift rebalance** — keep spot notional ≈ perp notional (drift comes from
  fills/rounding/deleverage).
- **kill switch** — `max_consecutive_errors` failed loops in a row → attempt to
  flatten everything.
- **rotation** (`rotate_enabled`, default off) — with `select_top_n` set, hold the
  N best (funding+earn) coins; once full, switch out of the weakest *mature* held
  leg when a candidate beats it by ≥ `rotate_margin_apr` ("much higher"). Min-hold +
  re-entry cooldown (`rotate_min_hold_hours`) prevent churn. Default off — naive
  rotation lost to always-hold in the v1 backtest, so it only fires on a large edge.
- **Kraken Earn stacking** (`earn_enabled`, default off) — the long-spot hedge
  otherwise sits idle, so when enabled the bot sweeps it into Kraken Earn **FLEX**
  (instant-unstake) strategies for staking APY on top of the funding, and
  deallocates just-in-time before any spot sell. Flex-only so the hedge stays
  exit-able. Selection then ranks coins on **funding + flex-earn** APR (e.g. AVAX:
  ~11% funding + ~10% earn). Validate the live APYs/asset-codes first with
  `python3 ../kraken_earn_probe.py --config config.yaml`, then flip it on.

Kraken Pro spot fees are covered by your KFEE credit; the HL leg pays ~1 bp maker
(carry isn't latency-sensitive). Run `leverage: 2.0` — margin = 50% of notional,
nowhere near liquidation with a live rebalancer.

## Files
- `config.example.yaml` — copy to `config.yaml` (gitignored), fill credentials.
- `exchanges.py` — `MarketData` (public HL), `HyperliquidPerp`, `KrakenSpot`. All honor `dry_run`.
- `strategy.py` — `decide(CoinState, Cfg) -> [actions]`. Pure logic, unit-testable.
- `main.py` — loop: read state → `decide` per coin → execute (or log in dry_run) → log a STATE snapshot → repeat.
- `requirements.txt` — `ccxt`, `hyperliquid-python-sdk`, `eth-account`, `PyYAML`.

## Run locally
```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml      # edit: keep dry_run: true, fill (or leave blank) creds
python3 main.py --config config.yaml --once     # one iteration
python3 main.py --config config.yaml            # loop
```
In `dry_run: true` the bot computes and **logs** every order it would place but
sends none. With credentials present it still reads real positions/balances;
without, it mocks them as flat. **Run dry for 1–2 weeks** and read the `STATE`
log lines before flipping `dry_run: false`.

## Going live (later)
1. Create an HL **API wallet** (not your main key), fund the HL perp account.
2. Fill `config.yaml`: `hyperliquid.account_address` + `hyperliquid.secret_key`,
   `kraken.api_key` + `kraken.api_secret`. Keep `config.yaml` gitignored.
3. Set `dry_run: false`. Start with one small asset (`BTC`, `notional_usd: 200`).
4. Watch `liq_room`, `delta`, `funding_apr` in the STATE logs.

## Deploy (TODO)
K8s/Helm chart mirroring `freqtrade/k8s/helm/freqtrade-bot` — Dockerfile +
deployment + secret (creds) + PVC (for `fc_state.json`) + `deploy.sh`. Not built yet.

## Known v1 simplifications
- HL orders are IOC-taker (~9 bp round-trip). Maker-with-fallback (post-only ALO,
  cancel + IOC after `maker_wait_seconds`) → ~3 bp round-trip, is a TODO.
- No precise perp/spot basis alert (would use `meta_and_asset_ctxs` markPx vs
  oraclePx). The discipline is "only unwind on your terms", so a basis spike
  triggers no auto-action anyway.
- `deleverage` cuts a fixed fraction of the position; a finer "restore exactly
  L×" calc is possible but this is a rare emergency path.
