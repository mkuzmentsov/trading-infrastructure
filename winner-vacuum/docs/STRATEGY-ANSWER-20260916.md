# "Find me a 5m crypto strategy" — the answer
**2026-09-16. Two rounds, four specialists, ~1.5M agent tokens, ~115 model configs, 81 archive rows
re-triaged. Nothing deployed.**

## The answer

**The strategy you already have is the strategy — and we now know exactly what it is, which we
did not before.** Two rounds of adversarial search found nothing better, but they replaced a folk
account with a measured one, and the measured one is actionable in three places.

> ### What the fleet actually is
>
> | population | n | realised | at the displayed ask | execution edge |
> |---|---|---|---|---|
> | **NON-swept** | **4,290 (97.7%)** | **+0.3910 c/sh** | **+0.4249** | **−0.034** |
> | swept ≥5c | 100 (2.3%) | +1.1071 | −51.6414 | +52.75 |
>
> **It is a modest PREDICTION edge — +0.391 c/share on 97.7% of fills, earned essentially AT the
> displayed ask.** Execution contributes nothing there. The whole "execution edge" is the 2.3% sweep
> tail (101% of it), its mechanism is **rescue not skill** (at the displayed ask those bars return
> −51.6 c/share because sweeps win 68% against a 96.6% base), and fleet-wide it is **one fill**.
>
> ⭐ And it lives in the **low-conviction** half of its own signal: **93% of 29-day net comes from
> `|est| < 2 bps`.** The fleet is not paid for being sure. It is paid for showing up where the book
> will trade.

## Why nothing better exists — four walls, each now a bound rather than a refutation

1. **Conviction is mechanically self-defeating.** Fill rate by `|est|`: **0.829 / 0.741 / 0.357 /
   0.083 / 0.018** — **46× unconditional, 23× holding ask band and tl fixed**. At `|est| ≥ 8` there
   is **not one takeable second in 21,938 observations**. *Our estimator resolves when the TWAP
   reconstruction resolves, and every maker on the same Chainlink ticks resolves at the same instant
   and pulls the offer — **conviction and withdrawal are the same event**.*
2. **The maker lane is closed twice over, in the venue's own unit.** Maker benefit is **exactly
   8.4·p(1−p)**; adverse selection normalised the same way runs **−20 at mid → −252 at 0.98**. The
   fee lever worked because mispricing shrinks *slower* than p(1−p); adverse selection shrinks
   slower too — **the same move that opened the taker lane closes the maker lane. The two walls are
   the same wall from two sides.** **0 of 16 band×era cells positive**, and a *perfect* canceller
   reaches zero in no band.
3. **The post-close pool is real and unreachable.** $211-264/day exists, but median depth ahead is
   **150,192 shares**, **P(print > depth) = 0.00%**, total overflow in 10 days **$0.00**, and the
   queue builds **504 → 111,681 shares in five seconds** against **11 shares/bar** of arriving flow.
4. **The fee cannot be cut and no subsidy exists.** Tiers are algebraically a fee-spend ladder
   (`wV ≡ 32.857 × fee`); even *Obsidian* flips no cell. Rewards are $0 on 5m crypto twice over.

## What to actually do — three things, in order

### 1. ⛔ Fix the `live_inflight` ratchet — this is not optional and not a strategy question
**eth and xrp have placed zero orders since 09-09; hype fires only below ask 0.598.** Three of seven
coins are out of the book from an in-memory counter that never decrements on the abandoned-bar path,
behind a `return` that does not log. **btc and sol are clear only because they restarted; bnb is one
bad bar away.** This is ~40% of the fleet switched off silently.
→ `incident-inflight-ratchet-20260915.md`. Two repairs, both the user's call.

### 2. ⭐ Cut clip size to k ≈ 0.5
Giving up **$4.68/day is undetectable** (detecting $4/day needs ~633 days). Zero-edge
**P(equity<$50) falls 31.5% → 14.0%** over the window needed to learn anything. ⚠️ Executable form is
`sh = max(5, int(k·req_sh))` — `LIVE_SIZE` is in **shares** with a hard 5-share floor, so naive
halving deletes 60% of fills and *raises* concentration.
**Judge on realised stake/day, not PnL.** Revert is a single helm key.

### 3. 🟡 Log the panel's feature block into `PF_TE_EVAL`
One additive, log-only recorder change turns **53,311 bars** of decision record from 16 fields into a
modellable panel. Every "underpowered" verdict in this program is waiting on day-clusters, and this
is the only change that buys them at zero research cost.

## The one thread still alive (OPEN, not a finding)

**Budget-neutral sizing by model confidence**: **+$2.448/day, t=+2.76**, all 7 coins positive,
weight-shuffle placebo **z=+3.77 (0/300)**, ex-top-5-rows +1.945. Its fatal objection was resolved —
**extra size does fill, φ(2) = 1.9176** measured with no fill model (a partially-filled FAK
identifies executable depth *exactly*; Kaplan-Meier on that identifies the distribution).
⚠️ **Still not deployable**: deflated **t = −0.32** over ~115 configs, the latency tell is unclean,
and 20 day-clusters is the detection floor. **It needs more days, not more analysis** — and the
portfolio side notes it buys return with variance (t unchanged 1.02→1.04) and adds 13 points of
zero-edge ruin.

## The honest bottom line

The fleet earns **$8.37/day at t = 1.25** and **cannot distinguish itself from zero on its own
29-day record**. As an income stream it is not worth running at any size; **as a position that is
already built and already correct, it is worth keeping small while the evidence accumulates.**

If it is still at t < 1.5 after 60 more days, the $8.37/day was 29 days of luck.
