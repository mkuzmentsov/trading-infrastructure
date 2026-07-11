# cur+2 bettor — losing-deal analysis & stop-loss feasibility (as of 2026-07-11)

Investigation only — **no code written**. Data: `CUR2_BET_SETTLE` events from the
live sol-cur2 + eth-cur2 pods, `filled>0 & live` only → **407 settled deals**
(205 won / 202 lost, total realized **−$2.88** all-time; +~$12 since the top-up).
Intra-bar paths reconstructed from Binance 1m klines of the target 5m bar.

## Mechanics reminder (what a "deal" is)
Bot rests a 0.50 BUY on the model's predicted side of the cur+2 5m market, fills
~10 min before the bar opens, then **holds to resolution — there is no exit today**.
Win = +$5 (10 sh), loss = −$5. The outcome is decided over the target bar
`[target, target+300]`. So any in-flight stop-loss can only act in those 5 minutes,
by selling the shares into the market at the then-current price.

---

## Finding 1 — the model's HIGH-conviction bets are the worst (pre-trade signal)
Win rate & PnL by conviction `|p_up − 0.5|`:

| conviction band | n | win% | PnL | $/bet |
|---|---|---|---|---|
| 0.000–0.005 | 38 | 47.4% | −$12.3 | −0.32 |
| 0.005–0.010 | 75 | **57.3%** | **+$55.0** | **+0.73** |
| 0.010–0.020 | 100 | 54.0% | +$33.8 | +0.34 |
| 0.020–0.030 | 124 | 47.6% | −$34.5 | −0.28 |
| **0.030+** | 70 | **44.3%** | **−$44.9** | **−0.64** |

The edge lives in a **mild-conviction band (~0.005–0.02)**. Beyond 0.02 the model is
anti-predictive — its most confident calls lose the most. Consistent with adverse
selection: when the model is very sure, the move is already visible to everyone and
our 0.50 rest gets filled by informed flow on the wrong side.

## Finding 2 — the loss is concentrated in eth-DOWN
| coin·side | n | win% | PnL |
|---|---|---|---|
| sol UP | 221 | 52.0% | **+$31.1** |
| eth UP | 58 | 51.7% | +$10.0 |
| **eth DOWN** | 127 | **46.5%** | **−$47.5** |
| sol DOWN | 1 | — | +$3.5 |

**eth-DOWN alone is basically the entire fleet loss.** The model over-predicts DOWN
on eth and is wrong more than half the time there.

## Finding 3 — clear time-of-day clustering
Worst hours (UTC): **04h** (30% win, −$49), **09h** (33%, −$40), **23h** (−$28),
**00h** (−$20). Best: 05h (+$40), 06h (+$39), 03h (+$30), 10h (+$25). Small n/hour
(~24) so treat as suggestive, not a hard schedule.

---

## Finding 4 — losers ARE identifiable mid-bar (stop-loss is viable in principle)
% of deals on the **losing side of the bar open** at the end of each minute:

| | min1 | min2 | min3 | min4 |
|---|---|---|---|---|
| sol losers | 57% | 67% | **76%** | 77% |
| sol winners | 26% | 23% | **15%** | 12% |
| eth losers | 68% | 68% | **80%** | 88% |
| eth winners | 38% | 31% | **27%** | 15% |

A **"exit if adverse at end of minute 3"** rule catches ~76% (sol) / ~80% (eth) of
losers while wrongly cutting ~15% / ~27% of winners.

**Magnitude sharpens it:** at min3, eventual *losers* are adverse by median **4.9 bps**
(p75 7.6, max 20.5) vs winners-wrongly-cut only **2.6 bps** (max 8.6). So a threshold
like *"stop only if adverse > ~4 bps at min3"* keeps most winners.

## Finding 5 — stop-loss EV depends on the mid-bar exit price (the key unknown)
Modeled EV of the min-3 stop (exit at price E per share, vs current baseline):

| exit price E | sol (base +$50) | eth (base −$35) |
|---|---|---|
| 0.20 | +$72 ✅ | −$74 ❌ |
| 0.25 | +$121 ✅ | −$23 ✅ |
| 0.30 | +$170 ✅ | **+$27** ✅ (eth turns positive) |
| 0.35 | +$219 ✅ | +$78 ✅ |

sol is helped at **any** plausible exit; eth needs **E ≥ ~0.25**. Both are realistic
if you can sell near the implied probability — but that is **not yet verified**.

---

## The catch / what to verify before coding
1. **Mid-bar liquidity is the whole ballgame.** The EV above assumes we can dump 10
   shares at ~0.25–0.35 two minutes before close. These 5m markets may be thin
   mid-bar; a market sell could get far less (or not fill). **Next step: record the
   cur+2 book depth + best bid during [target+120, target+240] for a sample of live
   bars** before trusting Finding 5. This is the #1 risk.
2. Exit price E here is *proxied* from the underlying's adverse move, not the actual
   Polymarket token price — measure the real token bid mid-bar.
3. Sample is small (407 deals, ~1.5 funded days) and net is ~flat; every effect is
   1–2σ. Re-run as fills accumulate.

## Two intervention families (record both; gates may beat the stop)
- **(A) Pre-trade gates — zero execution risk, likely the bigger win:**
  skip bets with `|p_up−0.5| > 0.02` (Finding 1), **skip eth-DOWN** (Finding 2),
  optionally de-weight 04h/09h/23h/00h (Finding 3). These *avoid* the losing deal
  entirely — no mid-bar liquidity needed. Simpler and safer than a stop-loss.
- **(B) In-flight stop-loss:** at ~min3 of the target bar, if adverse by > ~4 bps,
  market-sell the shares. +EV in the model (Finding 4–5) **iff** mid-bar exit ≥ ~0.25
  — gate on the liquidity check in #1 first.

Recommendation when we do build: do **(A) first** (cheap, addresses the worst losers
directly), then evaluate **(B)** only after verifying mid-bar book depth.
