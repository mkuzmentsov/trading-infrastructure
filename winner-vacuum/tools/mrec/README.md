# mrec v2 → parquet research pipeline (built 2026-09-06, notes §66)

Turns the raw recorder dumps in `every-tick-single/data/mrec/` into parquet and
replays vacmaker policies against them. Run in this order from a scratchpad dir
with a `pq/` subdir (paths are absolute at the top of each script — edit `OUT`).

| step | script | produces |
|---|---|---|
| 1 | `ev2pq.py meta` | `res/bar/rb.parquet` (resolutions, bar defs, REST reconciles) |
| 2 | `ev2pq.py ev` | `trades.parquet` (2.7M real prints: px, size, aggressor side, tx), `bookev.parquet` |
| 3 | `snap2pq.py` | `snapcur.parquet` (27.5M `cur`-market 10Hz rows + top-3 ladders) |
| 4 | `recon.py` | `cl.parquet` (1Hz Chainlink), `barrecon.parquet` (TWAP-60 strike/final/margin) |
| 5 | `panel.py` | `panel.parquet` — one row per (coin, bar, tl-second): **relay-lagged** live estimate, coverage, favourite ask/bid/ladders, realized outcome |
| 6 | `flow2.py` | `panelflow2/3.parquet` — causal trade-flow features + `dB5/10/20` (bid drop) |
| 7 | `polysim2.py` | policy replay with **tape-confirmed fills**; `sim()` takes a `veto=` callable |
| — | `askfate.py` | did a displayed ask get TRADED away or CANCELLED (uses the print tape) |
| — | `rb2.py` | RB rows incl. REST top-of-book, for presence/price agreement checks |
| — | `long2pq.py`, `longrecon.py`, `longpanel.py` | same for the 15m / 1h / 4h / 1d recorders |

## Two rules baked in — do not remove them
1. **Relay lag (bug #25).** `panel.py` gates the TWAP window at the SNAP row's own `cl_ts`, i.e.
   only ticks the recorder had already received (measured lag p50 2.13s). Filtering by wall-clock
   time instead makes every sim clairvoyant and reads ~+$3k/6d of fake profit.
2. **Tape-confirmed fills.** `polysim2.sim(tape=True)` counts a fire only if a real BUY print
   existed at ≤ our limit within 1.5s. Displayed asks overstate takeable supply (bug #23);
   the favourite has no ask at all in 83% of late-window seconds.

`lib.load_trades()` joins the print tape to resolutions and adds `tl`, `isw`, fees
(`0.07·p·(1−p)` per share), gross/net.

## 2026-09-06 evening additions (notes §68-§71)

| script | what it does |
|---|---|
| `lad2pq.py` | full **10-level** SNAP ladder extractor (cur role, tl≤26) → `lad10.parquet` |
| `shape2pq.py` | book-shape panel: top-3 ladders both sides both tokens + 5/10/20s lags |
| `simshape.py` | `polysim2` re-implementation on the shape panel, with a corrected `sweep=` cap |
| `exitsim.py` | post-entry exit simulator (4 exit fill models) — used to close the exit lane |

### ⚠️ THE HOUSE FILL MODEL — use this, not `polysim2.py`'s defaults (bug #27)
`polysim2.py` still defaults to `CLIP=8 / LADDER=16 / FILLW=1.5` and takes the best qualifying
print price. **The live fleet runs $24 / $48** (`chart/bots/*_vacmaker.yaml`), and price
improvement taken from a 1.5s forward window is borrowed from the future. The calibrated cell is:

- fill window **0.4s**, price-improvement cap **0¢** (fill AT the displayed ask),
- size **walked down the displayed top-3 ask ladder**, tape-confirmed,
- **CLIP=24 / LADDER=48**.

Scored against the fleet's own day closes for 09-02…09-04 (live **+$18.40 / 351 bars / 17 loss
bars**) it is the best of twelve cells on all three axes (**+$34.94 / 312 / 22**); the old cell
carries **34** loss bars. Implementation: `scratchpad/mine/calib.py`.
⚠️ The calibration is **aggregate only** — per coin it is anti-correlated with live (r=−0.63).
Never rank coins, or choose a pilot coin, from a replay.

### A third rule to bake in, alongside the two above
3. **Score the replay against live before quoting it.** A replay of a LIVE strategy has ground
   truth in `winner-vacuum/RESEARCH-LOG.md`. Match PnL, bar count and loss-bar count, and name the
   cell in the write-up.

## Paths (2026-09-10)

Every script now resolves the parquet dir from **`MREC_PQ`**, defaulting to a relative `pq/`.
The old hard-coded absolute paths pointed at a session scratchpad that no longer exists, which
silently broke `ev2pq/snap2pq/lib/recon/panel` and the whole `tickjump/` set.

```bash
export MREC_PQ=<repo>/every-tick-single/data/pq          # shared build, gitignored via data/
export PYTHONPATH=<repo>/winner-vacuum/tools/mrec
cd <repo>/every-tick-single/data/work                    # has a `pq` symlink — flow2/polysim2
                                                         # read 'pq/...' as a relative path
```

**Step 4a is missing from the table above**: `recon.py` READS `cl.parquet`, it does not create it.
Build it first — it is the dedup of the Chainlink tick embedded in every snapshot row:

```python
d = pd.read_parquet(f'{PQ}/snapcur.parquet', columns=['coin','cl','cl_ts']).dropna()
d['cl_ts'] = d.cl_ts.astype('int64')
d.drop_duplicates(['coin','cl_ts']).sort_values(['coin','cl_ts']).to_parquet(f'{PQ}/cl.parquet')
```

`panelflow.parquet` (the input `flow2.py` expects) is just `panel.parquet` — flow2 only reads
`coin/ws/tlk/side/fav_bid` from it. Copy it across; the script that originally emitted it under
that name was lost with the old scratchpad.

Build order that works end to end: `ev2pq.py meta` → `ev2pq.py ev` → `snap2pq.py` → cl.parquet
(above) → `recon.py` → `panel.py` → copy panel→panelflow → `flow2.py`.
