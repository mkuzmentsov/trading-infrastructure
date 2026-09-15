# ⛔ LIVE DEFECT: `live_inflight` ratchets up permanently and silently kills coins
**Found 2026-09-15 by the quant-analyst agent while looking for a selection effect.
Independently re-verified in this session. NOTHING DEPLOYED — both repairs are the user's call.**

## Status right now

| coin | leaked | headroom of $60 | can still fire? | pod age |
|---|---|---|---|---|
| **eth** | $47.52 | $12.48 | ⛔ **NO — dead since 09-09 19:59 UTC** | 15d |
| **xrp** | $47.52 | $12.48 | ⛔ **NO — dead since 09-09 19:59 UTC** | 14d |
| **hype** | $44.46 | $15.54 | ⚠️ only at **ask ≤ 0.598** | 15d |
| doge | $14.85 | $45.15 | degraded (fires at $5 clips) | 12d |
| bnb | $0 | full | ✅ one bad bar away | 15d |
| btc / sol | $0 | full | ✅ **only because they restarted** | 40h / 2d8h |

**Three of seven coins have been dead or crippled for six days.** The pods are `Running`, the WS is
ready, balance is $466.96, they presign every bar and still emit 30-58 `PF_TE_WHALE_DELAY`
decisions/day on takeable asks — and never fire. Nothing in any log says why.

## The bug

`winner-vacuum/chart/files/scripts/twapedge.py`, `settle_loop`:

```python
if up is None:
    if now > ws + BAR_SECONDS + 900:
        bar.settled = True            # <-- live_inflight NEVER decremented
        _event("PF_TE_SETTLE_ABANDONED", ...)
    continue
```

`live_inflight` is incremented on every fire (lines 489, 551, 1188, 1348) and decremented **only on
the normal settle path** (lines 852, 864). When a bar's outcome is unresolvable for 15 minutes the
abandoned path marks it settled and `continue`s — **skipping both decrements forever**. The counter
is in-memory, so it ratchets monotonically until `live_inflight + clip > LIVE_INFLIGHT_CAP` ($60)
blocks every fire.

⚠️ **And the block is silent.** `_whale_fire` (line 1328):
```python
if self.live_inflight + sh * ask > LIVE_INFLIGHT_CAP:
    return                            # no event
```
Its two sibling call sites both log `PF_TE_LIVE_SKIP` with `inflight=`. **This one returns bare** —
which is why six days of total inactivity produced no diagnosable signal.

**Trigger**: a Gamma outage on **2026-09-09 19:00-20:30 UTC**. `PF_TE_SETTLE_ABANDONED` counts on the
pods: xrp 4, doge 4, btc 2, eth 2, sol 2, hype 2, bnb 1 — every coin has leaked at least once.

## Verification (independent of the agent that found it)

1. **Code**: the increment/decrement asymmetry and the bare `return` read exactly as described. ✔
2. **Point prediction**: hype's $15.54 headroom implies it can only fire at `26 sh × ask ≤ $15.54`,
   i.e. **ask ≤ 0.598**. Its only recent fire — **2026-09-15 19:39 UTC — was `seen_ask 0.59`,
   `req_sh 26`, $15.34.** Inside the ceiling by 20 cents. ✔
3. **Why btc/sol are fine**: pod ages **40h and 2d8h** vs 14-15d for the latched three. A restart
   zeroes the in-memory counter. They are not healthy, they are *recently rebooted*. ✔

## What it cost — deliberately not quantified in dollars

The only available fill model **reads the sign backwards** (−$49.53 against an actual +$56.22 on the
four coins that kept trading over the same five days — bug #46 again), so no dollar counterfactual is
credible. What *is* measurable: the opportunity set is intact — **402 gated eth/xrp/hype decisions in
5 days, 98.0% side-correct, 62 of them at ask < 0.90** — and on their own historical ledger rates,
restoring them is worth **−$1.19/day naively, +$0.57/day excluding xrp's single −$42.94 day**.
Indistinguishable from zero.

⭐ **So the exposure is not the P&L. It is that the ratchet takes coins permanently, invisibly, and
one at a time** — and bnb is one abandoned bar from joining them, while btc and sol are only clear
because they happened to restart.

## The two repairs (separate, both need the user's decision)

1. **Code** — decrement `live_inflight` on the abandoned path, and make the `_whale_fire` cap-block
   log `PF_TE_LIVE_SKIP` like its siblings so this can never again be silent. Arguably also
   persist/reconcile the counter rather than trusting in-memory state — *"every local counter is a
   cache"* ([[openmm-5m-maker]], five reconciliation bugs).
2. **Ops** — clear the three latched pods. A restart zeroes the counter, but per §26 a restart is
   itself a behavioural event and should land at a UTC-00:00 rollover.

## Unrelated config drift found in the same pass

**`eth` alone has `PM_TE_FIRST_SKIP_LO=0` / `_HI=0`** where the other six carry `0.90` / `0.98` —
drift from the 08-31 deploy. Verified live across all seven pods. It is also an accidental 10-day
control arm for the mid-band skip, and it came out **positive**: 223 attempts / 40 fills / **+$15.43,
1 loss**. Removing eth takes the pooled 0.90-0.98 clip-1 cell from −$81.56 to **−$124.87**.
