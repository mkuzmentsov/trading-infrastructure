# pm_btc — ML model for the Polymarket BTC 5m bot

Trained on the bot's own `logs-training.jsonl` snapshots. Predicts **P(bar
resolves UP)** from mid-bar features (BTC momentum, PM book state, time-in-bar).

Complementary to the `ai/` root's Kraken-OHLCV model: that model only sees
5m candles at bar-close. This one sees live bot state mid-bar, so it can
react to PM book movement the OHLCV model has no visibility into.

## Install

```bash
cd ai/pm_btc
pip install -r requirements.txt
```

## Build the dataset

From one or more runs' logs. Each snapshot → one row; label = bar outcome.

```bash
python prepare_dataset.py \
  --logs-glob '../../polymarket/k8s/helm/polymarket-btc-bot/pm-btc-logs_*/logs-training.jsonl' \
  --output outputs/pm_btc_dataset.parquet
```

## Train

```bash
python train.py \
  --dataset outputs/pm_btc_dataset.parquet \
  --output  outputs/pm_btc_model.txt \
  --report  outputs/pm_btc_report.json
```

Uses `GroupKFold` on `condition_id` so rows from the same bar never split
across train/val — no leakage. Reports:

- log-loss, Brier, AUC (OOF)
- reliability buckets (10 bins) — shows calibration at a glance
- per-feature gain importance

## Evaluate

Hypothetical PnL vs. a book-implied baseline:

```bash
python evaluate.py \
  --dataset outputs/pm_btc_dataset.parquet \
  --model   outputs/pm_btc_model.txt \
  --min-edge 0.05 --min-price 0.15 --max-price 0.40
```

## Wiring into the bot (not done yet)

When/if the model beats the closed-form signal on calibration AND hypothetical
PnL, expose a `SIGNAL_MODEL=ml` env flag in `math_signal.py`:

```python
# math_signal.generate_signal
if os.getenv("SIGNAL_MODEL") == "ml":
    from pm_btc.predict import MLSignal
    _ml = MLSignal("/app/data/pm_btc_model.txt")
    p_up = _ml.predict_p_up(snapshot) or fair_probability_up(...)
```

Copy the model into the pod:

```bash
kubectl cp ai/pm_btc/outputs/pm_btc_model.txt \
  polymarket/<pod>:/app/data/pm_btc_model.txt
```

## Notes / caveats

- **Small sample bias.** With <2000 bars, the model overfits easily. `min_data_in_leaf=50` is deliberately conservative. Re-train weekly.
- **Regime risk.** A model trained during low-vol days will misprice high-vol days. Log its live calibration and retrain when drift appears.
- **Label proxy.** We use the last logged BTC price inside the bar as the resolution; the true oracle round may differ by a few seconds. Bars without a snapshot in the final 30s are dropped.
- The ML model fixes *entry selection*. It does NOT fix execution bugs (unreachable TPs, book collapses, late cuts). Keep the rule-based exit logic regardless.
