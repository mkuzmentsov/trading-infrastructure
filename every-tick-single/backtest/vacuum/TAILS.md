# Tail scan: "buy at <= 0.05, redeem at 1.00" — Sat 01 Aug 2026

Scope: 6 coins, **2,911 resolved 5m bars** of mrec (Thu 30 Jul 13:00 →
Sat 01 Aug 05:00 UTC). Script: `tails.py` + the per-observation check below.

Both doors are shut. The two regimes fail for different reasons.

## 1. POST-CLOSE (the settlement snipe) — the opportunity does not exist

**0 of 2,911 bars** had the *winning* token offered at ≤ 0.05 after close.
Not rare. Zero.

Cheap post-close asks are abundant — 75% of all post-close asks are ≤ 0.05 —
but they are on the **loser**. Validated directly: median post-close ask is
**0.900 on the winner** vs **0.010 on the loser**, and the winner usually has
*no* ask at all (nobody offers a token that is about to pay $1).

This is the same thing the live bots measured independently:

| btc-snipe, lifetime | bars | lock correct | lock wrong |
|---|---|---|---|
| a ≤5c ladder was present (fillable) | 13 | **0** | **13 (100%)** |
| no ladder (unfillable) | 330 | 314 (95%) | 16 |

So a cheap ladder on our locked token is near-proof that we locked the
**loser**. Ladder-presence is an adverse-selection signal, not an opportunity.
btc-snipeb never saw a single fillable bar in 312.

⚠ This contradicts the earlier `settlement-snipe-edge` finding (8% of bars,
10–18k winner-shares at 1–3c). That was derived by matching data-api trades to
the raw recorder; this scan reads the quoted book directly. Whatever those
trades were, the winner is not *offered* at ≤5c in the post-close book, so a
resting-or-taking bot on our timeline cannot reach them.

## 2. PRE-CLOSE (the tail lottery) — priced fair to rich, so buying loses

Measured **per observation** (ask as quoted at a fixed moment, "did that token
win?"), which is the only unbiased way to ask it:

| quoted at | observations | winners | ROI on 1sh each |
|---|---|---|---|
| t−5s | 2,234 | 8 (0.36%) | **−71.8%** |
| t−15s | 1,782 | 11 (0.62%) | **−58.0%** |
| t−60s | 1,051 | 16 (1.52%) | **−37.7%** |

By price at t−5s: 0.01 → 0.27% win (needs 1.00%), 0.02 → 0.44% (needs 2%),
0.03 → 0.00% (needs 3%), 0.05 → 2.63% (needs 5%). Every bucket negative.
The two mildly positive cells anywhere in the table (+1.32pp at 0.04/t−15s,
+0.30pp at 0.05/t−60s) rest on 5–7 winners out of ~90–140 — noise.

The deep 1c tail is the worst of all and the most abundant (avg ~3,500 shares
offered): 0.09–0.27% win against a 1% breakeven.

### ⚠ Methodology warning — a bias that faked a +190% edge

A first pass took, per bar per side, the **cheapest ask seen anywhere in the
bar** and bucketed by that price. It reported +189.7% ROI with win rates of
41.8% at 0.03 and 46.2% at 0.04. That is **minimum-selection bias**: a side
whose cheapest-ever ask was 0.04 spent the rest of the bar far more expensive,
so its win probability reflects its *average* price, not 4c. Pairing the
minimum price with the full-bar outcome manufactures an edge from nothing.
Always price per observation, at the instant of the quote.

## Verdict

Neither variant is tradable on this data. `btc-snipe` and `btc-snipeb` were
scaled to 0 on Sat 01 Aug 2026. Their realised loss was **$0.00** — every live
order had been rejected under the $1 venue minimum (see commit 35b5398), so
the bots never actually traded the −EV set they were pointed at.
