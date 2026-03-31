# BTC 5m Direction Model

All commands run from the `ai/` directory. Outputs go to `outputs/`.

## Train a new model (two-stage — recommended)

```bash
# 1. Generate features per asset separately
python generate_features.py --input inputs/kraken/BTC/XBTUSD_5m_2013-2025.csv --output outputs/kraken/BTC/BTCUSD_features.csv
python generate_features.py --input inputs/kraken/ETH/ETHUSD_5m.csv            --output outputs/kraken/ETH/ETHUSD_features.csv

# 2. Pretrain on BTC+ETH, fine-tune on BTC only
python train_staged.py \
  --pretrain outputs/kraken/BTC/BTCUSD_features.csv \
             outputs/kraken/ETH/ETHUSD_features.csv \
  --finetune outputs/kraken/BTC/BTCUSD_features.csv \
  --target   target_dir_1bar \
  --output   outputs/model_staged.txt
```

## Train a single-asset model

```bash
# 1. Generate features
python generate_features.py \
  --input inputs/kraken/BTC/XBTUSD_5m_2013-2025.csv \
  --output outputs/features.csv

# 2. Train
python train_model.py \
  --input outputs/features.csv \
  --target target_dir_1bar
```

Other targets: `target_dir_3bar` (15 min), `target_dir_12bar` (1 h), `target_dir_48bar` (4 h).

## Backtest

```bash
python test_model.py --model outputs/model_staged_<timestamp>.txt --edge 0.08
```

## Retrain on latest live data

```bash
python retrain.py --model outputs/model_staged_<timestamp>.txt
```

## Deploy to bot

Run from repo root (requires cluster access):

```bash
kubectl cp outputs/model_staged_20260330_105047.txt -n polymarket \
  $(kubectl get pod -n polymarket -l app.kubernetes.io/instance=pm-btc-1 -o name | head -1 | sed 's|^pod/||'):/app/data/model.txt
```

```bash
python generate_features.py --input inputs/kraken/BTC/XBTUSD_5m.csv --output outputs/kraken/BTC/features.csv 
python generate_features.py --input inputs/kraken/ETH/ETHUSD_5m.csv --output outputs/kraken/ETH/features.csv 
python generate_features.py --input inputs/kraken/SOL/SOLUSD_5m.csv --output outputs/kraken/SOL/features.csv
 
```

```bash
python train_staged.py --pretrain outputs/kraken/BTC/features.csv outputs/kraken/ETH/features.csv outputs/kraken/SOL/features.csv --finetune outputs/kraken/BTC/features.csv --target target_dir_1bar  --output outputs/model_staged.txt 
```