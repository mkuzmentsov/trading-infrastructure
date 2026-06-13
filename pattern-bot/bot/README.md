# pattern-bot

A chart-**pattern** trading bot. It scans candles for a pattern, and on a
confirmed signal it **reports to the console and opens a trade**. First pattern:
**double top / double bottom**. Trades **Hyperliquid perps** now; swap the
`exchange:` key to move venues later (Kraken Futures is stubbed).

The detector and trade-geometry are *pure functions* shared verbatim by the
backtester and the live bot, so sim and live can't drift. Detection is **causal**
(only past candles), so backtests are honest.

## How it works
- **Double top** → bearish → **short**: two ≈equal swing highs with a trough
  (neckline) between them; confirmed when a bar *closes below* the neckline.
- **Double bottom** → bullish → **long**: mirror image; confirmed on a *close
  above* the neckline.
- **Entry**: at the confirmation bar's close (IOC taker).
- **Stop**: just beyond the 2nd peak/trough (`stop_buffer_pct`).
- **Target**: measured move — the pattern height projected from the neckline
  (or a fixed R:R via `target_mode: fixed_rr`).
- **Size**: risk `risk_per_trade_pct` of equity to the stop, capped by
  `max_leverage`.

## Files
- `patterns.py` — pure detector (`detect(candles, cfg) -> PatternSignal`). Run it
  directly (`python3 patterns.py`) for self-tests.
- `strategy.py` — pure trade logic: `plan_trade()` (entry/stop/target/size),
  `check_exit()` (stop/target/timeout), `decide()` (live step).
- `broker.py` — `Broker` ABC + `HyperliquidBroker` (longs+shorts, dry-run aware);
  `KrakenFuturesBroker` stub for the later switch. `make_broker(cfg)`.
- `main.py` — live loop: candles → detect → decide → execute + console reporting,
  with state persistence (`pattern_state.json`) and a kill switch.
- `../fetch_data.py` — pull HL OHLC candles → `../data/<COIN>_<interval>.parquet`.
- `../backtest.py` — replay candles through the same pure functions; report stats.

## Quickstart
```bash
pip install -r requirements.txt

# 1. self-test the detector
python3 patterns.py

# 2. fetch history + backtest
python3 ../fetch_data.py --coins BTC,ETH,SOL --interval 1h --months 12
python3 ../backtest.py --coins BTC,ETH,SOL --config config.yaml --trades

# 3. run live loop in DRY-RUN (logs only, no orders)
cp config.example.yaml config.yaml      # keep dry_run: true
python3 main.py --config config.yaml --once    # one iteration
python3 main.py --config config.yaml           # loop
```
In `dry_run: true` the bot reads real public prices and **paper-trades** —
logging every `PATTERN` / `OPEN` / `CLOSE` / `STATE` line but sending no orders.

## Going live (later)
1. Create an HL **API wallet** (not your main key) and fund the perp account.
2. Fill `config.yaml`: `hyperliquid.account_address` + `hyperliquid.secret_key`
   (and `vault_address` if trading a sub-account). Keep `config.yaml` gitignored.
3. Set `dry_run: false`. Start with one coin and a small `risk_per_trade_pct`.
4. Watch the `STATE` / `OPEN` / `CLOSE` logs.

## Switching to Kraken Futures (later)
Implement `KrakenFuturesBroker` in `broker.py` against `ccxt.krakenfutures`
(method-by-method TODOs are in the class docstring), fill `kraken_futures` creds,
set `exchange: kraken_futures`. Nothing else changes — strategy/backtest/loop are
venue-agnostic.

## v1 simplifications
- Live management uses our **own** stop/target (HL has no native attached stop) —
  the bot checks the mark each loop and closes via IOC taker when hit. A venue
  stop-order could be added later.
- Entry price is approximated by the mark at execution (good enough for 1h); a
  fill-aware version would re-read the position next loop.
- One position per coin; new signals are ignored while a position is open.
