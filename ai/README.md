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
kubectl cp outputs/model_v2a_20260331_084015.txt -n polymarket \
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

---

## HuggingFace Foundation Model Backtests

Zero-shot BTC 5m direction backtests against live Binance data.
Models live in `ai/hf-models/`. Each script is self-contained.

### Prerequisites

```bash
# All scripts
pip install torch numpy pandas requests

# Per model
pip install "chronos-forecasting>=2.0"   # Chronos-2
pip install tirex-ts                      # TiRex
# TimesFM 2.5 & Sundial: timesfm2_5 is not yet in the released transformers package.
# Install from source:
pip install git+https://github.com/huggingface/transformers.git
```

### Models

| Script | Model | Size | Backend | Key arg |
|---|---|---|---|---|
| `test_chronos2.py` | Chronos-2 | 120M | PyTorch | `--context 512` |
| `test_tirex.py` | TiRex | 35M | ONNX (xLSTM) | `--context 256` |
| `test_timesfm.py` | TimesFM 2.5 | — | Transformers | `--context 512` |
| `test_sundial.py` | Sundial | 128M | Transformers | `--context 512 --samples 50` |

### Run

```bash
# Quick smoke-test (default args: 700 candles, edge≥0.05)
python test_chronos2.py
python test_tirex.py
python test_timesfm.py
python test_sundial.py
```

```bash
# Longer backtest with custom settings
python test_chronos2.py --candles 1000 --context 512 --edge 0.05 --batch 32
python test_tirex.py    --candles 1000 --context 256 --edge 0.05 --batch 64
python test_timesfm.py  --candles 1000 --context 512 --edge 0.05 --batch 32
python test_sundial.py  --candles 1000 --context 512 --samples 50 --edge 0.05 --batch 16
```

### Arguments (all scripts)

| Arg | Default | Description |
|---|---|---|
| `--candles` | 700 | 5m candles fetched from Binance |
| `--context` | 256–512 | Lookback bars fed to model |
| `--edge` | 0.05 | Min \|P(UP)−0.5\| to count as a bet |
| `--batch` | 32–64 | Inference batch size |
| `--samples` | 50 | (Sundial only) generated samples per tick |

### Output format

All scripts print the same table as `test_model.py`:

```
====================================================
  Chronos-2 Backtest  (183 × 5m candles ≈ 15h)
====================================================
  Total ticks evaluated : 183
  Ticks with edge≥0.05  : 120  (65.6%)
  Accuracy (all ticks)  : 52.46%
  Accuracy (bet ticks)  : 53.33%
  ...
  Edge bucket breakdown:
  ...
  Last 30 ticks:
  ...
```

### Model directory layout

```
ai/hf-models/
├── chronos-2/        # amazon/chronos-t5-large-v2 or similar
├── tirex/            # NX-AI/TiRex
├── timesfm-2.5/      # google/timesfm-2.5-500m or similar
└── sundial/          # thuml/sundial-base or similar
```