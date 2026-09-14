# Bar autopsy — `bnb-updown-5m-1789384200` (2026-09-14 11:10–11:15 UTC)
**Built 2026-09-14 with `.claude/skills/pm-bar-dash`. Nothing deployed.**
Dashboard: <https://claude.ai/code/artifact/7bcd5e77-67ca-4625-ae06-f5381be05fc5>

**A WIN: +$9.06** — bnb's best fill of the day (16 fills, **0 losses**, +$23.13; this bar is 39%
of it). The user picked this bar; I did not select it for its outcome. That matters, because it
is the first non-selected bar the freshness lever met, **and it refutes it.**

## 1. ⛔⛔ THE TAIL-FRESHNESS LEVER IS REFUTED ON ITS FIRST HONEST TEST

Two hours ago I wrote up "fill H1's unobserved tail with the live Binance deviation instead of
the stale Chainlink tick" as an open lever, on two bars where it would have avoided a loss, and
flagged that both were selected *because* they lost. **This bar is the control, and the lever
fails it.**

At the fire (tl 15.3) Binance read **+4.633 bps** against the Chainlink tick's **−0.165** — a
**4.8 bps disagreement against our DOWN side**, the same signature as the btc −$20.80 bar (8.8 bps
against). Applying the substitution:

| tail filled with | H1 | what the bot would have done |
|---|---|---|
| **Chainlink last tick, −0.165 bps (what it used)** | **−0.538** | fires DOWN → **+$9.06** ✅ |
| Binance **at** the fire, +4.633 bps | **+0.582** | **fires UP** (gate 0.5455) → **loses** ❌ |
| the tail that actually happened | −0.227 | — |

Venue truth **−0.2307 → DOWN**. The lever does not merely veto this winner; it **takes the
opposite side and loses**.

⭐ **Why it fails — the substitution assumes full, instant convergence, and Chainlink does not
converge.** BNB's Chainlink did rise after the fire, but only to **+1.5 bps** against Binance's
+4.6; the 60-second average never came close to crossing. Compare btc 1789393200, where Binance
+6.93 was followed by Chainlink reaching +6.6 — near-total convergence. The convergence *fraction*
is the whole model, it differs per bar and per coin, and fitting it on three bars is fitting noise.

**Status: the naive form is dead. Do not re-derive it.** What survives is only the weaker,
untested statement that the Binance–Chainlink disagreement at fire time may carry *some*
information — and note that on the three bars in hand the disagreement points the same way on a
loss (btc, 8.8 bps against) and on a win (bnb, 4.8 bps against). Magnitude alone does not separate
them. [[latency-ceiling-closed]] is looking more right than I allowed for.

## 2. The bar

| | |
|---|---|
| strike / final (`PF_TE_VERIFY`, err 0.0 bps) | 721.1109069 → 721.0942737 |
| margin | **−0.2307 bps** → **DOWN** |
| our fill | DOWN, displayed ask **0.99**, filled **32.82 sh @ 0.7239**, $23.76 |
| result | **+$9.06** ledger / **+$8.60** net of fee, ROI **+38%** |
| est at fire | **−0.550** vs `eff_thresh` **0.5455** — cleared by **0.0045 bps** |

Third razor-thin gate crossing in three autopsied bars (doge 0.004, btc comfortable, bnb 0.0045).
The threshold is doing a lot of work at the margin, and that is worth a proper look at some point —
**not** from three bars.

## 3. The same sweep as the btc loss, opposite sign

The displayed ask was a solid **0.99 × 100**. During the order's **574 ms** round trip the ask
collapsed to 0.71; because the limit sat at 0.99 the dollar-denominated FAK swept the entire
falling stack and filled **32.82 shares at 0.7239** — **27¢** of "price improvement",
`PF_TE_TOXIC_BRAKE` tripped, bar closed to further clips.

That is *physically the same event* as btc 1789393200 six hours later: book collapses mid-flight,
FAK eats it, brake fires. There: **−$20.80**. Here: **+$9.06**.

⭐ **What separates them is whether the collapse was informed** — and the tell is the favourite's
own **bid**:

| | displayed ask | fav bid, 6 s before → at fire | dB6 | outcome |
|---|---|---|---|---|
| btc 1789393200 | 0.79 | 0.96 → 0.82 | **−0.140** | −$20.80 |
| **bnb 1789384200** | **0.99** | **0.80 → 0.93** | **+0.130** | **+$9.06** |
| doge 1789403700 | 0.72 | 0.52 → 0.10 | **−0.420** | −$3.65 |

An ask that collapses while the bid *rises* is someone pulling liquidity. An ask that collapses
while the bid *falls with it* is the market repricing. This is [[bid-drop-veto]]'s thesis, and it
is now 3-for-3 on direction across two losses and a win.

## 4. The bid-drop veto leaves this winner alone — twice over

1. **Out of scope by ask.** `seen_ask 0.99` is not `< PM_TE_BIDDROP_MAX_ASK 0.98`, so the rule
   never evaluates. This is exactly the ask-conditioning `strat-losstail-veto-20260910` §9 added
   after finding the un-conditioned form "deletes the ≥0.90 bid-drop class — 83 fills, +$46.87,
   containing both era-scale sweep windfalls". **This bar is one of those windfalls.**
2. **It would have passed anyway**: `dB6 +0.130`, `dB10 +0.210`, `dB20 +0.160` — all positive.

So across the three autopsied bars the veto blocks both losses (doge dB6 −0.42, btc −0.14 and not
anchor-sensitive) and allows the win on its own signal. ⚠️ Still **n=3**, two of them selected for
losing; this is not a measurement and the case remains for the `PF_TE_BIDDROP` **log-only arm**,
not for shipping blocking.

## 5. Odds and ends

- Same-bar cross-coin: at bar **1789393200** bnb won DOWN **+$8.31** while btc lost DOWN
  **−$20.80** on the same clock. Coins are not redundant even when the side agrees.
- Recon vs venue: −0.359 vs **−0.2307** bps, `sobs/fobs` 56/56 — side agreed here, magnitude off
  by 0.13 bps. Consistent with gotcha 3.
- Market-wide the bar was thin: 45 prints, $381 notional, takers **−$8.91** — and we took $23.76
  of it. On a bar this thin our own clip is most of the flow.

## 6. Reproduce

```bash
cd <repo root> && source ./.dev-env-source
python3 .claude/skills/pm-bar-dash/build_dash.py bnb bnb-updown-5m-1789384200 --outdir <scratch>
python3 .claude/skills/pm-bar-dash/assemble.py <scratch>/dash.json <scratch>/bar.html
```
