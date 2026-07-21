---
name: ett-pull-raw
description: Pull the full-state 100ms WS snapshot archives (raw book + trades + signals) recorded IN the every-tick-single tail 5m (v1) pods, to a local dir for strat backtests. Use whenever a backtest/analysis needs tick-level market state (maker-fill realism, exit paths, signal replay) — not just the decision events (that's ett-pull-events).
---

# ett-pull-raw

The full-state recorder (`ws_recorder.py`, `run_recorder`) runs **inside the v1
tail 5m bots** (`<coin>-tail-every-tick-single`, ns `every-tick-single`), started
by `execution.runner.TakerRunner` when `RECORD_SNAPSHOTS=true` — off the SAME
feeds the bot trades on (no separate recorder fleet). Each writes a full-state
snapshot every 100ms while a bar is live:
`/app/logs/raw/<coin>-YYYYMMDD-HH.jsonl` (current hour, uncompressed) and
`...-YYYYMMDD-HH.jsonl.gz` (rolled hours, 7-day rolling retention on the PVC).

Coins: btc eth sol xrp bnb doge. Deploy/pod name: `<coin>-tail-every-tick-single`.

## Row schema (NDJSON, UTC hour buckets)
- `BAR`  (once per bar): `{t, coin, ws, ev:"BAR", cid, q, up, down, end}` — condition_id, token ids (up/down), question, bar end ts.
- `SNAP` (every 100ms): `{t, coin, ws, tl, ev:"SNAP", spot, spot_age, open, sig, lead_bps, z, ftrue, fup, momz, ub, ua, ubs, uas, db, da, dbs, das, uL, dL, trd}`
  - `ub/ua/ubs/uas` = UP token best bid/ask + sizes; `db/da/dbs/das` = DOWN token.
  - `uL/dL` = tail-zone ask ladders `[[price,size],...]` (prices ≤0.25), cheapest first — the depth a taker/maker actually sweeps. Empty near 50/50 (no tail yet); populates as a favorite emerges.
  - `trd` = new trade prints since the last row `[[ts, "U"|"D", price, size, side],...]` (from CLOB trade feed) — the crosses a 100ms snapshot could otherwise miss.
  - `lead_bps, z, ftrue, fup, momz, sig` = the diffusion signals (same math as fav_taker) so any strat's decision can be replayed offline without recomputing.

## Steps

1. Kube context MUST be Hetzner first (silently hits AWS EKS otherwise):
   `cd <repo root> && source .dev-env-source && kubectl config current-context`
   → must print `hetzner-k3s-cluster-master1`.

2. See what each pod holds (hours available, sizes):
   ```
   for c in btc eth sol xrp bnb doge; do
     echo "== $c =="; kubectl exec -n every-tick-single deploy/${c}-tail-every-tick-single -- \
       sh -c 'ls -la /app/logs/raw/'
   done
   ```

3. Pull to a local dir (default the scratchpad, or `every-tick-single/data/raw/`).
   Current (uncompressed) hour — `cat`, no `-i`:
   ```
   DIR=<dir>; mkdir -p "$DIR"
   for c in btc eth sol xrp bnb doge; do
     for f in $(kubectl exec -n every-tick-single deploy/${c}-tail-every-tick-single -- sh -c 'ls /app/logs/raw/*.jsonl 2>/dev/null'); do
       kubectl exec -n every-tick-single deploy/${c}-tail-every-tick-single -- cat "$f" > "$DIR/$(basename $f)"
     done
   done
   ```
   Rolled `.gz` archives — pull binary through base64 (kubectl `cat` on a `.gz`
   is safe, but pipe to file; do NOT let the terminal mangle it):
   ```
   for c in btc eth sol xrp bnb doge; do
     for f in $(kubectl exec -n every-tick-single deploy/${c}-tail-every-tick-single -- sh -c 'ls /app/logs/raw/*.jsonl.gz 2>/dev/null'); do
       kubectl exec -n every-tick-single deploy/${c}-tail-every-tick-single -- cat "$f" > "$DIR/$(basename $f)"
     done
   done
   # sanity: gzip -t "$DIR"/*.gz
   ```
   For one coin / one day only, filter the `ls` glob to `*-<YYYYMMDD>-*`.

4. Read locally (mix of .jsonl and .jsonl.gz):
   ```python
   import glob, gzip, json
   def rows(dir, coin=None, ev=None):
       pat = f"{coin or '*'}-*.jsonl*"
       for f in sorted(glob.glob(f"{dir}/{pat}")):
           op = gzip.open if f.endswith(".gz") else open
           for line in op(f, "rt"):
               e = json.loads(line)
               if ev is None or e.get("ev") == ev:
                   yield e
   ```

## Gotchas
- ALWAYS pull the current-hour `.jsonl` BEFORE any helm upgrade/restart of a tail
  pod — the live hour is on the PVC but an in-flight rotation could gzip it mid-pull.
- Same pod, DIFFERENT files: raw snapshots go to `/app/logs/raw/`, decisions to
  `/app/logs/logs-training-events.jsonl` (that's `ett-pull-events`). Both on the
  tail bot's PVC. Only the `-tail-` (v1 5m) bots record — enabled via
  `RECORD_SNAPSHOTS=true`; tail15 and any experiment variants do not.
- Volume is ~0.45 GB/day/coin raw (~45 MB/day gz). Pull only the coins/days you
  need; a full 7-day × 6-coin pull is ~2 GB gz.
- Retention is 7 days (`RETENTION_DAYS` env). Pull anything you want to keep
  long-term; the PVC prunes older buckets automatically.
- `sig`/`z`/`momz` in the first ~30s of a pod's life can be null/degenerate until
  the Binance minute-bar history warms — same warmup caveat as the bots.
