# every-tick-single — Polymarket maker-rebate paper bot (single-asset)

One resting maker bid per 5m bar per coin on Polymarket's up/down markets.
PAPER fleet (no credentials, no real orders) generating the datasets that the
EXPERIMENTS.md registry decides go-live questions with. Fork of the retired
two-sided every-tick-both (see git history) — strategy findings live in
PLAN.md / EXPERIMENTS.md.

## Architecture

```
src/
  main.py            event loop, feeds wiring, event log (+ midnight rotation)
  config.py          env config (validated at import)
  core/              market data + infra
    pm_ws.py         Polymarket market ws: book, trade prints (trade_print events)
    btc_ws.py        Chainlink RTDS spot feed
    binance_ws.py    Binance spot feed (+ minimal 1m bar tracker)
    gamma.py         market discovery (deterministic 5m slugs)
    positions.py     position store
    telegram.py      alerts (inert without creds)
  engine/            execution engines
    paper_book.py    simulated book: print-based fills, bracket lifecycle,
                     settlement, event emission (bar_snapshot, settles)
    live_book.py     real CLOB engine (post-only maker, kill switch) — unused
    clob.py          signed order helpers (post_only GTC, FAK)      in paper
    user_ws.py       authenticated fill stream (live only)
    redemptions.py   on-chain redemption sweep (live only)
  strategy/
    maker_rebate.py  the strategy: fixed post-only entry, TP, hold-to-expiry
    side_rules.py    pluggable side pick (alternate | signal)
    math_signal.py   fair p_up estimate
    base.py, factory.py
backtest/sim.py      EXPERIMENTS.md sims (print-exact fills, regime grid, salvage)
tests/
  unit/              characterization tests (fill engine, bracket, side rules,
                     startup gate, snapshot cadence, rotation, live_book smoke)
  test_backtest_integration.py   frozen per-date baselines (tests/data/<date>/)
  run_all.py         full suite, isolated interpreters
  fetch_day.py       pull a date's rotated archives from the pods
  gen_baseline.py    deliberate baseline regeneration
chart/               helm chart; code ships as a ConfigMap (deploy.sh syncs
                     src/ -> chart/files/scripts/); image = deps-only pm-btc-bot
```

## Operating

- Deploy (needs Hetzner context + USER CONFIRMATION): `source .dev-env-source && ./deploy.sh [coin ...]`
- Tests: `python3 tests/run_all.py`
- Data: each pod writes `/app/logs/logs-training-events.jsonl`, rotated+gzipped
  at UTC midnight, 30 days kept. `tests/fetch_day.py <date>` pulls archives.
- Experiments: EXPERIMENTS.md — run records with conditions; adoption needs a
  joint re-sim + fresh out-of-sample day.
