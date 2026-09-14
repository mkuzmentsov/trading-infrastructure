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
- ⚠️ **both gates are on price, not just the print**: the tape print must be at
  **px <= the displayed ask**, AND the fill size is capped by displayed depth **at prices <= the
  ask**. Walking the full top-3 ladder without that price constraint — or treating the cap as a
  flat "limit 0.99" — reads **−$65 to −$84** on 09-02…04 instead of +$34. This exact
  misreading cost an agent a day's work on 2026-09-10; the wording used to say only "walked down
  the displayed top-3 ask ladder", which admits it.
- **CLIP=24 / LADDER=48**.

Scored against the fleet's own day closes for 09-02…09-04 (live **+$18.40 / 351 bars / 17 loss
bars**) it is the best of twelve cells on all three axes (**+$34.94 / 312 / 22**); the old cell
carries **34** loss bars. Implementation: `scratchpad/mine/calib.py`.
⚠️ The calibration is **aggregate only** — per coin it is anti-correlated with live (r=−0.63).
Never rank coins, or choose a pilot coin, from a replay.

### ⛔⛔ 2026-09-10: THE HOUSE CELL DOES NOT REPRODUCE LIVE PnL — validated against the pod ledger

Do not trust any `$/day` or `losses/day` that comes out of a replay. The cell above reproduces
**bar count and loss-bar count** and nothing else. Measured against the fleet's own
`PF_TE_WHALE_ORDER` ledger (1,994 fires / 1,141 fills, read-only from all 7 pods, which
reconciles the RESEARCH-LOG day closes to within **$0.55 every day**):

| | replay | live |
|---|---|---|
| 09-02…09-09 gross | **−$82** | **+$203** |
| 09-09 loss bars reproduced | **2 of 7** (3 of the sim's 5 are bars the fleet never fired) | — |

**The sign inversion has one dominant cause: the live FAK is DOLLAR-denominated, the replay is
share-denominated.** 39 sweep bars (**3.8% of bars**) carry **44% of the era's gross**
(+$234 wins / −$139 losses; one clip took **1,524 shares**). The house cell caps a bar at ~30
shares, so it **deletes the windfalls and keeps the losses**. Independently corroborated: the btc
live fill ledger already found the stale-ask sweep is ~40% of btc profit.

Three further defects, any one of which breaks an absolute claim:
- **22.4% of live fills land ABOVE the displayed ask** — the bot sends `ask + LIVE_PX_BUFFER`.
  A replay that refuses to fill above the displayed ask cannot see them.
- **The 0.4s tape window rejects 42% of fills that demonstrably happened.** 1.5s recovers 96%.
  So the 0.4s/1.5s choice trades one bias for another; neither is "correct".
- ~~**The estimate reconstruction fails the live gate on 28% of real decisions** and takes the
  OPPOSITE side on 10.6%~~ ⛔ **RETIRED 2026-09-15.** That measured the *pre-bug-#45* estimator.
  Joined row-for-row on `(coin, ws, tlk)` against the bot's own logged `est_bps` (141/141 hits),
  the corrected `est_live` reproduces the bot to **corr 0.9937, median |Δ| 0.003 bps, side agreeing
  99.3%**, and displayed ask vs `seen_ask` to a **median |Δ| of 0.0000**. The reconstruction is
  faithful; do not cite the 28% figure.
- ⚠️ **`polysim2.thresh=0.10` is a FOURTH wrong default** — live is `pmTeThreshBps=0.5`. Running
  at 0.10 inflates bars ~1.6×, which is plausibly why the published cell appeared to match live's
  351 bars in the first place.

**Unresolved conflict, stated honestly**: on 09-02…04 the long-duration agent reproduced
**+$33.79 / 307 / 22** from this README while the validation agent, applying `px <= ask` to both
the print and the depth walk, got **−$91.65 / 320 / 22**. Bars and loss bars agree; PnL does not.
Until someone rebuilds `calib.py`, **treat the published +$34.94 as unverified.**

Live ground truth for those days: **+$18.40 / 351 bars / 17 loss bars**.

### What a replay IS still good for
Rates, base rates, and RELATIVE A/B where both arms share the fill model and neither depends on
sweep sizing. **For anything $-denominated, and for all loss-tail work, use the pod
`PF_TE_WHALE_ORDER` ledger instead — it needs no fill model at all** and reconciles to the day
closes within $0.55. That is how the loss-tail veto (§ strat-losstail-veto-20260910) was measured.

### ⚠️ Tape defects — filter before you count anything
- **6-hour resolution outage 09-09 18:55 → 09-10 00:55 UTC** (~400 unlabelled bars, verified at
  source). Do NOT patch it with `barrecon.pred` — that is circular.
- **`zec` appears in `res`/`panel` but is not traded.** Exclude it.
- **bnb/doge carry an 08-25/26 tail** plus a full 09-01 — a different era (bug #24).
- Practical window: **use 09-02 … 09-09 only.**

### Panel sampling — the good news
1Hz retention does **NOT** preferentially drop violent bars (100% ask presence on loss bars), so
there is no optimism bias from missing bars. But the retained ask matches the bot's within 0.5¢
only **15% of the time on sweeps** vs 71% on quiet bars. A 0.4s rebuild buys **price fidelity,
not bar count**.

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


## 2026-09-15: three sources, three jobs — do not substitute one for another

| source | n | days | what it settles |
|---|---|---|---|
| `panel.parquet` (mrec+Binance) | 4,321 bars | **3** | *which feature* — full book, ladders, flow, Binance |
| **`evals_live`** (`PF_TE_EVAL`) | **53,311** bars | **30** | *does it hold up* — the bot's own tl≈28 decision record on **every bar it saw, fired or not**; `sign(twap_h1_bps)` is 97.75% accurate |
| `fills.parquet` (`WHALE_ORDER`+`LIVE_SETTLE`) | 4,390 fills | 29 | *is it worth money* — real prices, real PnL, no fill model |

⭐ **`PF_TE_EVAL` is the answer to G=3.** It is 12.4× the panel's bars and 10× its day-clusters, and
it is a genuine decision-time information set. MDE on `E[y−mid]` falls **0.76 pp → 0.22 pp**. Price:
one `tl`, no ladder, no flow, no Binance.

⚠️ **`bars_live` (`PF_TE_SETTLE`) is NOT a decision-time feature** — it fires *after* the bar, so its
`point_bps`/`h1_bps` read 99.74% accurate. Settlement reconstruction only.

⚠️ **`clip` means two different things.** On a *matched* `WHALE_ORDER` it is the 1-based clip index
(joins to `LIVE_SETTLE`); on an *unmatched* one it is the count filled so far — one bnb bar has 17
consecutive unmatched attempts all stamped `clip: 0`. Join on it unconditionally and you attach
settlements to attempts that never filled.

⚠️ **Bug #16 lives here too**: joining `WHALE_DELAY` outcomes via `LIVE_SETTLE` silently conditions
on *the bar having later produced a fill* (2,295 of 6,270, and blocked-bars-that-never-filled are
not a random subset). Use `PF_TE_SETTLE` — 6,233 of 6,270, unconditional.

### Measured live fill rates by displayed ask (8,496 attempts, 30 days — supersedes the interpolations)
`<0.55` **n=9, do not use** · `0.55-0.75` **0.173** · `0.75-0.90` **0.220** · `0.90-0.95` **0.512** ·
`0.95-0.98` — · `>=0.98` **0.749** (bug #23's 75% reproduced exactly).

⚠️ **17.8% of live fills land ABOVE the displayed ask and 14.5% below it** ⇒ any supply census built
on displayed quotes is wrong in **both** directions.

### Era break (bug #24)
Attempts fall from **250-400/day in August to 62-78/day from 09-10**. The 3-day panel window sits
entirely inside the low-activity era.
