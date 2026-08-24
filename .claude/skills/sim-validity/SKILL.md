---
name: sim-validity
description: Backtest/simulation discipline for PM crypto updown research — dataset checks, fill-model validity controls, bug ledger workflow. Invoke BEFORE writing a new sim and WHENEVER a sim result looks surprising or two sims disagree.
---

# Sim validity — how to build, validate, and debug backtests in this repo

Authoritative knowledge: `winner-vacuum/docs/backtesting.md` (script
inventory, conventions, full bug ledger) and `winner-vacuum/docs/README.md`
§3 (dataset coverage table) + §4 (checklist). Read both now if not already
in context.

## Before writing a sim
1. Pick the dataset from README §3 and CONFIRM its window coverage ≥ your
   sim's quoting window (postI is late-window ONLY — bug #2).
2. Model adaptive strategies with mid-relative prices, never flat levels
   (bug #3).
3. Plan controls INTO the run: a no-op config (skew=0), a queue-haircut
   pair (QH=0 vs QH=0.01), and matched-vs-residual PnL split.
4. For 7-day raw scans in-pod: use the streaming finalize pattern
   (`kl/mm2_stream.py`) — accumulators only, finalize past watermark, or
   you get OOM 137 (bug #5).

## After it runs — accept the result ONLY if
- Stricter queue haircut LOWERED PnL (else fill model broken, bug #4a).
- Deep/aggressive fills show LOWER win% (else artifact, #4b).
- Result is delay-SENSITIVE where latency should matter (#4c).
- It doesn't contradict a neighboring sim on the same data by an order of
  magnitude (if it does, at least one is broken — find which before using
  either).
- Zero-counts were verified by histogramming raw WITHOUT prefilters
  (bug #1: compact JSON `"trd":[[` — no space).
- Residual/directional luck is split out (91%-UP-week trap).

## When a bug is found
Append to the ledger in `winner-vacuum/docs/backtesting.md` §3 in the same
session: date, symptom, root cause, fix, prevention rule. Update any
verdicts that the bug invalidated (docs/README decision map + strategy file
+ RESEARCH-LOG correction entry). Wrong verdicts propagate into memory —
fix `~/.claude-personal/.../memory/` entries too.

## Ground rules
- Paper validates plumbing, never EV (bug #9). Live-tiny beats paper for
  fill physics.
- The wallet is accounting truth, never bot counters.
- A sim whose result isn't written into RESEARCH-LOG + the strategy doc
  didn't happen.
