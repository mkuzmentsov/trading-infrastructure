# generic-crypto-image

Shared **deps-only** base image for the crypto trading bots. Replaces the old
`pm-btc-bot` image. Bot code is injected at runtime via a Helm ConfigMap mounted
at `/app/scripts` (unchanged pattern) — so code edits are a `helm upgrade`, never
an image rebuild. The image only changes when a dependency changes.

## What it bundles
- **Exchange / Polymarket SDKs:** `websockets`, `py-clob-client`, `py-clob-client-v2`, `requests`
- **On-chain:** `eth-account`, `eth-abi`, `eth-keys`, `eth-utils` (redemptions + relayer)
- **ML / data:** `numpy`, `pandas`, `scipy`, `scikit-learn==1.9.0`, `lightgbm` —
  so bots can load trained models (e.g. the every-tick-single cur+2 direction
  models) directly, no per-bot image build.

`python:3.12-slim` + `scikit-learn==1.9.0` match the model-training environment
(`every-tick-single/backtest/fiftycent`) so pickled models load without version drift.

## Build / push
```bash
./build.sh            # tag 0.1, linux/amd64, pushes mkuzmentsov/generic-crypto-image:0.1
./build.sh 0.2        # new tag when deps change
```

## Used by
- `every-tick-single` — set `image.repository: mkuzmentsov/generic-crypto-image`
  in `every-tick-single/chart/values.yaml`.
