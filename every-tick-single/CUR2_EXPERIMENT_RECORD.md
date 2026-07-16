# cur2 experiment — record & post-mortem (closed 2026-07-15)

The cur+2 "50c bettor" (`cur2_bettor.py`): each 5m boundary, predict the cur+2 bar
with a frozen sklearn HistGradientBoosting model and rest a passive **0.50 BUY** on
the predicted side. Live on the shared Polymarket wallet `0xD632…1b2F`, $5/bet,
$50/day loss cap.

## Verdict: **DECOMMISSIONED — structural loser.**

Net result across the whole experiment: old flat-0.50 bots lost **−$156** (eth −$122),
replaced by the debias-fixed cur2fix fleet which lost a further **~−$160**
(sol −16, eth −35, xrp −48, doge −61 since the last restart). Wallet trajectory
peaked ~$174 → ~$94. No coin was ever net-positive; no green regime existed.

## Why it lost — this is the load-bearing finding

**Adverse selection on the passive 0.50 rest is the whole story, not model quality.**

- Measured live: of 18 unfilled bets, **17 were bets we were RIGHT on** (would have won)
  and only 1 was a loss we dodged. doge: all 11 non-fills were winners.
- Fill-rate split by outcome across all coins: **losers fill 96–100%, winners 60–91%.**
- Mechanism: our resting 0.50 bid is lifted only when a seller crosses down to us —
  which happens when the token is moving *against* our side. When we're right, the
  token drifts up and away and nobody takes the rest → the winner is left on the table.
- Consequence: realized (filled) win rate is far below the model's ex-ante accuracy.
  17 wins (~+$85 at $5) were missed while the losers all filled = the entire −$160.

## Model facts (so we don't re-litigate)

- OOS walk-forward directional accuracy ≈ **51.4% all bets, ~54% on the conviction
  slice** (|p−0.5|>0.02). Real but tiny.
- **Horizon sweep cur+0…7** (`backtest/fiftycent/horizon_sweep.py`): every horizon
  sits ~51%, none materially better. Predicting further out does NOT help.
- High-conviction bets were **anti-predictive live** (~44% win) — the opposite of the
  backtest. The edge that exists lives in the low-conviction band and is fragile.
- **btc** could not clear 52% OOS (deepest/most efficient book) — recommended not deployed.
- Debias fix (threshold at rolling-288 center + conviction gate) bought regime
  robustness, **not more edge**. It did not change the verdict.

## Why "just predict better" cannot save the resting-maker design

- Polymarket taker fee = `0.10 · p · (1−p)`, **peaks at 2.5¢/share exactly at 0.50**.
- Crossing the spread to guarantee fills (the `fav_taker` taker design) pays that fee →
  breakeven win rate jumps to ~53% → **net-negative after fees OOS**. Already tested.
- The maker **rebate at 0.50 is only ~0.35¢/share** (20% of the 0.07 fee weighted by
  p(1−p)) — two orders of magnitude smaller than the 50¢ cost of a directionally wrong
  filled bet. Rebate cannot compensate for adverse selection at a single 0.50 rest.

## The one untested lever

Post a **more aggressive maker bid (e.g. 0.51, still below the ask → no taker fee)**.
Breakeven only 51%; fills more of the winners the 0.50 rest missed; residual adverse
selection shrinks but does not vanish. Unknown whether net-positive — needs a backtest /
paper test, not an armchair verdict. This is the basis for the successor experiment
(every-bar rebate harvester incl. BNB + BTC).

## Successor tested: every-bar ~50c rebate harvester — ALSO DEAD (2026-07-15)

Tested the "trade every bar, rest ~0.50, harvest rebates, just need a coin-flip"
idea directly on 43k+ bars of real OHLC per coin (`backtest_rebate_sim.py`,
`data_bnb.csv` added). Results across **btc/eth/sol/xrp/doge/bnb**:

- Passive 0.50 rest fills ~91% of bars but **filled win-rate is only 44.8–45.8%** —
  below 50% on every coin. Two-sided net = **−$1.5 to −$1.8 per bar**.
- Rebate at 0.50 ≈ **$0.035 per 10-share fill** — ~100× too small to cover a $5
  wrong bet. It cannot close a 4–5pt win-rate gap.
- **Resting deeper is WORSE:** conditional on the underlying dipping 0.1% below open,
  it closes back up only **13–22%** of the time (bnb 13.5%, btc 15.8%, sol 22.2%).
  The intrabar path is **momentum/continuation, not mean-reversion.**

Root cause (now proven, not asserted): a resting maker BUY fills only when price
moves toward it (against its side); intrabar momentum then continues that move → the
fill is structurally adversely selected at **every depth**. Two-sided harvest is
doubly adverse (fill UP on dips that close down AND DOWN on pops that close up).
**No prediction model and no resting price fixes this** — it's microstructure.

**Implication:** ≥50% *filled* win rate is unreachable with any resting-maker design
on Polymarket UpDown. Rebate harvest is not viable here. The only side of the momentum
that wins is the **continuation (taker) side** — buy the direction the move is already
going — which pays the 2.5¢ taker fee + a worse price, and is only +EV if the token
lags the underlying (latency edge, see `latency/` + chainlink-delay-edge notes).
That is a different project (taker momentum + latency), not this one.

## Artifacts

- Code: `src/cur2_bettor.py`, `src/strategy/cur2_predictor.py`, `src/strategy/cur2_models.py`
- Backtests: `backtest/fiftycent/{horizon_sweep,eval_gate,debias_test}.py`
- Configs: `chart/bots/{sol,eth,xrp,doge}_cur2fix.yaml` (releases uninstalled 2026-07-15)
- Prior related: `CUR2_STOPLOSS_ANALYSIS.md`, `INTRABAR_INVESTIGATION.md`
