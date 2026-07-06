# pm-rebates-farmer — profitability improvement plan

## Diagnosis (live, 2026-07-06)
Three live versions all hover/bleed. Root cause is clear from the positions:
- **Both-fill pairs** (UP@0.50 + DOWN@0.49, complete set) earn **+$0.10 + rebates** —
  risk-free but tiny.
- **Single fills** (one leg fills, the other doesn't complete) are directional; pre-open
  they're ~50/50 but a loser costs **−$4.90**. One losing single wipes ~50 both-fill pairs.
- Fills arrive in **partial pieces** (4.27, 5.84 sh) so even "both-fill" windows end up
  **unbalanced** (UP 10 / DOWN 4 = net long 6 = directional).

So the whole game is: **maximize balanced both-fills, and make single-fills ≈ flat instead
of −$4.90.** Everything below serves that.

---

## Tier 1 — attack the single-fill loss (biggest lever)

### T1.1 Single-fill cut (pair-completion timeout) ⭐
If one leg fills and the pair isn't completed within N seconds, **cut the filled leg**
(sell back to the book / taker-exit) before it can go adverse. Pre-open the price is
~0.50, so cutting costs ~spread, not −$4.90. Turns the −$4.90 tail into ~−$0.02.
- Needs **fast fill detection** → the websocket (`pm_ws` user channel) instead of 5s polling.
- Config: `FARM_PAIR_TIMEOUT_SECS` (e.g. 30–60). Expected impact: removes the dominant loss.

### T1.2 Balanced sizing / inventory matching
Fills are partial. Keep the pair **delta-neutral**: when UP fills X, cap/resize the DOWN
leg to also target X (and vice versa); cancel the excess. Never hold a net position bigger
than the smaller leg. Eliminates the "UP 10 / DOWN 4" directional residue.

### T1.3 Cut on adverse move (hard stop for singles)
If a single leg is stuck and the market moves against it past a threshold (e.g. bid ≤ 0.30),
taker-exit immediately. Backstop for T1.1 when the pair genuinely can't complete.

---

## Tier 2 — trade only the good windows (game selection)

### T2.1 Balanced-book gate
Only place when **both sides can rest at ≥ 0.49** (book near 50/50). Skip windows where
one side's ask is already ≤ 0.48 pre-open — those are leaning and likely to single-fill
adversely. Fewer trades, higher both-fill rate.

### T2.2 Liquidity gate
Skip windows with a thin pre-open book (low depth / few recent trades) — fills there are
worse and rebate volume is low. Prefer btc (deepest) and the busiest windows.

---

## Tier 3 — capital velocity & scale

### T3.1 Merge complete sets early
When both legs fill (complete set), **CTF-merge back to USDC immediately** instead of
holding to expiry. Frees capital in seconds → more rebate cycles per dollar (throughput,
not per-trade edge). Matters when scaling. (Merge is a contract call, not an order.)

### T3.2 Multi-coin
Add eth/sol/xrp (`FARM_COINS`). More markets = more rebate volume + diversification of the
single-fill risk across uncorrelated books. Only after T1 makes single-fills safe.

### T3.3 Size tuning
Rebate scales ~linearly with filled size; the arb is fixed per pair. Once net ≥ 0, raise
`FARM_SHARES` to lift rebate income (bounded by account + per-window capital).

---

## Tier 4 — measurement (do first, it's cheap)

### T4.1 Structured fill log
Log every fill/both-fill/single-fill/cut/settle to jsonl (emptyDir is fine) so we can
actually measure: both-fill rate, single-fill win rate, cut effectiveness, rebate/fill.
Right now the farmer has minimal logging and we're reading balance snapshots — we can't
tell which change helped. **This gates evaluating everything above.**

### T4.2 Realized-rebate tracking
Pull the nightly MAKER_REBATE credit and divide by filled volume → the true rebate/share.
Confirms whether rebates can cover the residual single-fill drag.

---

## Sequencing
1. **T4.1** (logging) — so we can measure.
2. **T1.1 + T1.2** (websocket single-fill cut + balanced sizing) — the core fix.
3. **T2.1** (balanced-book gate) — cut bad windows.
4. Re-measure. If net ≥ 0 with rebates: **T3.2 multi-coin + T3.3 size + T3.1 merge** to scale.
5. If still negative after T1+T2: the pre-open edge is too thin to clear real fill costs
   (consistent with all prior findings) — retire the farmer, conclude the market is
   efficient to within fees + execution.

## Honest prior
Every measured edge in this project has died to execution. T1.1 (single-fill cut) is the
one genuinely-untested lever with a real mechanism. If it doesn't flip the net, nothing in
Tiers 2–3 will — they're amplifiers of an edge that must first exist.
