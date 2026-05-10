---
name: PM BTC 1h profitability plan 2026-05-10
description: Structured 4-phase plan to fix structural bleed (−$363 corpus, 47% WR, needs 72% WR). Phase 1 = signal calibration knobs; Phase 2 = exit fixes; Phase 3 = empirical model calibration; Phase 4 = strategic pivots.
type: project
---

## Context

Live corpus (6 bundles, ~260h): structurally negative. Bot wins 47–53% WR; needs 72% to break even at 0.65–0.70 entry prices. Root cause: Gaussian `_norm_cdf` calls "96% confident" (z=3, shrinkage=0.92) on nearly every trade; actual WR at those extremes is 50–63%.

**Corpus at time of writing:** 5 prior bundles (111h / 22h / 7h / 26h / 27h) + new 76.2h bundle (20260507_091151).

**Why:** payoff is asymmetric against us at any entry > 0.50. Max upside at entry 0.70 = $0.30/share; max downside = $0.70/share → needs 70% WR just to break even. Model says it has 96% confidence; market (and reality) say ~55%.

---

## What is ruled out — do NOT re-litigate

- **Skim threshold retune** — production (1080s, 0.99) is global corpus optimum
- **SMART_MAX_SIGMA** — works on old 5-bundle corpus (+$48 replay), fails on 27h and 76.2h bundles (−$18, −$22). Two consecutive regressions; shelve.
- **Entry-band (CEIL/FLOOR) sweeps** — bot reroutes around static price gates; prod (0.30/0.70) wins every time
- **Chop ratio gate** — CHOP 3–5 is actually a corpus winner; signal non-monotonic
- **Hour-of-day filter** — too few trades per window (n=43–49), likely regime artifact
- **Kelly sizing change** — bet cap binds for all trades; lowering just halves wins+losses proportionally
- **min-elapsed gate** — marginal ROI but negative abs PnL; not a quality filter

---

## Phase 1 — Signal calibration (cheap, replay-testable, already plumbed)

Both knobs exist in `math_smart.py` and are currently undertested.

### 1a. Lower `SMART_SHRINKAGE` (currently 0.92)

```python
# math_smart.py:263
p_up = 0.5 + SMART_SHRINKAGE * (raw_p_up - 0.5)
```

At 0.92: z=3 → p_up = 0.96. At 0.75: z=3 → p_up = 0.87. Fewer trades pass `SMART_MIN_EDGE`; those that do have a smaller edge claim and smaller position losses when wrong.

**Sweep:** `{0.70, 0.75, 0.80, 0.85, 0.92}` × 6 bundles = 30 replay runs.

### 1b. Lower `SMART_PUP_Z_CAP` (currently 0 = disabled, defaults to z=3.0)

```python
# math_smart.py:261-262
pup_z_clip = SMART_PUP_Z_CAP if SMART_PUP_Z_CAP > 0 else 3.0
raw_p_up = _norm_cdf(_clip(z, -pup_z_clip, pup_z_clip))
```

At cap=1.5: raw_p_up bounded to [0.067, 0.933] — directly fixes fat-tail overconfidence at the source. At cap=1.0: bounded to [0.159, 0.841].

**Sweep:** `{1.0, 1.2, 1.5, 2.0}` × 6 bundles = 24 replay runs.

Can be swept jointly as a grid with 1a. Ship whichever cell wins on ≥4/6 bundles with no individual regression > $20.

---

## Phase 2 — Exit fixes (medium effort, well-motivated by corpus)

### 2a. `smartSalvageRequirePeakFlatMax` 0.05 → 0.30

Trade 23 (DOWN 0.67 → 0.04, −$21) is the canonical case: peaked at 0.89 (peak−entry=0.22 > 0.05), so salvage_floor was gated out. On 1h bars a 0.22 peak can fully revert — the 0.05 threshold is a 15m-derived value that doesn't hold at 1h timescales.

Proposed: allow salvage_floor when `peak_bid − entry_price ≤ 0.30`. Positions that peaked > 0.30 above entry are deep-ITM — don't salvage those (they usually resolve). Positions in the 0.05–0.30 band are the reversion candidates.

**Sweep:** `smartSalvageRequirePeakFlatMax ∈ {0.05, 0.10, 0.20, 0.30, 0.40}` × 6 bundles.

### 2b. Drawdown-from-peak rule (new code required)

Exit if `peak_bid − current_bid > 0.40`. Would have caught trade 23 at bid ~0.50 (saving ~$15 vs the −$21 outcome).

**Risk:** clips winners with a normal mid-bar dip then recovery. Must sweep to verify no regression on the skim winners (which often dip then rip to 0.99).

**Implementation:** add to `manage_position` loop in `math_smart.py`, controlled by `SMART_DRAWDOWN_FROM_PEAK` env var (0 = disabled).

---

## Phase 3 — Empirical model calibration (most work, most durable)

### Why

All Phase 1 knobs are approximations of the same fix. The real fix is replacing the broken Gaussian calibration with observed win rates.

### How

1. From 6-bundle corpus `logs-training.jsonl`, bin all closed trades by `entry_p_up` (e.g. 0.80–0.85, 0.85–0.90, 0.90–0.95, 0.95+)
2. Measure actual WR and mean PnL per bin — this is the empirical calibration curve
3. Options for applying it:
   - **Lookup table correction**: replace `_norm_cdf(z)` output with `empirical_p_up[z_bucket]`
   - **Logistic recalibration**: fit `actual_p_win = logistic(a * raw_p_up + b)` on corpus trades
   - **Effective min-edge gate**: if empirical WR at this p_up < breakeven_WR(entry_price), skip

### Expected data
- Prior corpus: 271 trades across 187h (enough for 5–6 meaningful p_up buckets)
- Add 76.2h bundle: ~348 total trades

**Why:** all Phase 1 knobs are trying to approximate the effect of this. Do it directly.

---

## Phase 4 — Strategic pivots (if Phases 1–3 don't move the needle)

### 4a. Raise `SMART_MIN_Z_EARLY` further (currently 2.2)

Already moved 2.0 → 2.2 and halved trade count with big ROI lift (+8.1% → +19.4% on 2-bundle corpus). Another raise to 2.5–3.0 concentrates further on highest-conviction bars. Trade-off: may make bot too inactive (< 1 trade/day).

### 4b. Evaluate cheap-side entries (bid < 0.40)

At entry 0.35: max upside = $0.65/share, max downside = $0.35/share → payoff 1.86:1 in our favor. Only needs 35% WR to break even. The current bot bets the expensive side (bid > 0.65) which needs 72% WR. If BTC signal is directional, betting the cheap side when the market disagrees might have better EV. Different strategy but same infrastructure.

### 4c. End-of-bar only entries

Most losses happen on entries with > 40 min remaining (big move budget = big potential loss). Restricting to last 15–20 min of bar caps downside while the signal is already resolved. `SMART_MIN_ELAPSED_SECS` (currently 0) or a `SMART_MAX_SECS_LEFT` (not yet plumbed) could implement this.

---

## Execution order

| Priority | Action | Effort | Expected impact |
|---|---|---|---|
| **1** | Sweep `SMART_SHRINKAGE × SMART_PUP_Z_CAP` on 6 bundles | 1h | High — direct calibration fix |
| **2** | Sweep `smartSalvageRequirePeakFlatMax` 0.05→0.30+ on 6 bundles | 30min | Medium — targets trade-23 pattern |
| **3** | Build empirical WR calibration table from corpus | 2–4h | High, structural |
| **4** | Implement + sweep drawdown-from-peak gate | 2h | Medium |
| **5** | Evaluate cheap-side entry / end-of-bar-only | research | Unknown |

## How to apply

- Always sweep across all 6 bundles before shipping; single-bundle motivation has burned us 4× already.
- Gates on **persistent regime features** (like sigma) work better than **bar-local features** (entry price, time elapsed) because the bot can't reroute around persistent blocks.
- Ship only if ≥4/6 bundles win and no individual bundle regresses > $20 absolute.
- After any Phase 1 ship, re-check Phase 2 sweep — calibration changes may shift which exit trades fire.