# pattern-bot — Kubernetes deploy

Same pattern as `funding-carry/k8s`: the bot **code** is mounted from a ConfigMap
(populated from `pattern-bot/bot/*.py` by `deploy.sh`), the **config** (with creds)
from a Secret, and **state** (`pattern_state.json`) lives on a PVC. The image only
carries Python + deps. One replica (`Recreate`) — never two, or it'd double-trade.

## Image: reuses the funding-carry image (no build needed)
The chart points at `mkuzmentsov/funding-carry-bot:0.2`, which already has every dep
pattern-bot needs (hyperliquid-sdk, eth-account, PyYAML, and requests via the HL SDK;
we don't use ccxt). The bot code is mounted from the ConfigMap, not baked in, so the
image is just a Python+deps base and is shareable across bots — **no build/push step**.

If you ever want a dedicated image, `pattern-bot/k8s/Dockerfile` is a ready fallback:
```bash
cd pattern-bot/k8s && docker build -t mkuzmentsov/pattern-bot:0.1 -f Dockerfile . && docker push mkuzmentsov/pattern-bot:0.1
# then set image.repository/tag in helm/pattern-bot/values.yaml
```

## Deploy
```bash
cd pattern-bot/k8s/helm
cp bots/pb_btc_1.yaml.example bots/pb_btc_1.yaml     # gitignored
# edit bots/pb_btc_1.yaml: HL API-wallet creds, telegram token/chat_id, dry_run

./deploy.sh pb_btc_1        # rsyncs bot/*.py → chart, helm upgrade --install
kubectl logs -f deploy/pb-btc-1 -n pattern-bot
```
`deploy.sh` re-syncs the code and the deployment re-rolls on any code/config change
(checksum annotations), so to ship a tweak: edit `bot/*.py` or `bots/<name>.yaml`,
re-run `./deploy.sh <name>`.

## Go live
1. Run with `dry_run: true` first; confirm the `STATE` logs show real prices and you
   get the `🤖 pattern-bot started` Telegram message.
2. Set `dry_run: false` in `bots/<name>.yaml`, re-run `./deploy.sh <name>`.
3. Start small (the config sizes 25% margin × 2× = 50% notional of the HL balance).

## Teardown
```bash
./destroy.sh pb_btc_1       # flatten any open position FIRST — uninstall abandons it
```

## Notes
- Defaults (patterns, sizing, params) live in `helm/pattern-bot/values.yaml` under
  `botConfig` (mirrors `bot/config.example.yaml`). Per-bot overlays in `bots/<name>.yaml`
  deep-merge over them — usually you only set creds + `dry_run` there.
- Credentials never get committed: `bots/*.yaml` is gitignored (only `*.yaml.example` is kept).
