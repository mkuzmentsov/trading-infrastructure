# pm-common — shared Polymarket bot modules

The generic execution layer used by every bot (only COIN / BAR_SECONDS differ
per bot):

- `execution/tickbus.py`   — feed → eval-loop wake-up bus
- `execution/fastclient.py`— FastExec: warm CLOB session, per-bar prewarm,
                             presigned FAK orders (paper + live)
- `execution/runner.py`    — TakerRunner: event-driven bot harness (feeds,
                             market prefetch/roll, ctx building, telemetry)
- `execution/events.py`    — rotating JSONL event log (daily gzip, 30d keep)

Projects consume it via a relative symlink (e.g.
`every-tick-single/src/execution -> ../../pm-common/execution`), and deploy
scripts rsync with `--copy-links` so the chart ConfigMap ships real files.
Modules import the consuming app's flat `config` module at runtime (the
deploy layout puts everything in one directory).
