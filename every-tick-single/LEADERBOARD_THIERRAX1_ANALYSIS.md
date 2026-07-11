# How @thierrax1 makes money on Polymarket (as of 2026-07-11)

Wallet `0xf8af03f1e68ee7162db8983f0d6dd0dc869854c6`. Reverse-engineered from the
Polymarket data-api (positions + activity) and the user-pnl API (leaderboard source).

## The numbers (real, from Polymarket's own PnL feed)
Cumulative PnL **$213 → $19,086 over ~33 days** (2026-06-09 → 07-11).
- **7 down-days / 33** (79% green), **max drawdown from peak only ~$1,250** (~6.6%).
- **Accelerating**: early days +$100–400, recent days **+$1,000–3,375/day** — he
  scales size as the bankroll compounds. Steady, low-variance growth — exactly as
  described.
- Keeps **~$115 standing inventory** — profit is realized/withdrawn, fast turnover.

(Note: naively summing `cashPnl` over his 8,674 position rows gives −$54k — a data-api
artifact: it zeroes *redeemed winners* to $0 and shows them as total losses. Use the
user-pnl API, not position sums, for this trader.)

## What he trades
The **crypto 5-minute "Up or Down" markets** — SOL, XRP, BTC, DOGE, ETH, BNB.
**The same markets our cur2 bettor trades.** He is not in anything else.

## How he trades — the mechanism
- **100% taker BUYs** (470/470 in-sample are BUY, 0 SELL) + REDEEMs. He never rests
  orders and never sells; he crosses the spread to buy, holds to resolution, redeems.
- **Trades DURING the live 5m bar** (e.g. buys at 15:11 UTC into the 11:10–11:15 ET
  market — 1 min in), reacting to the intra-bar move.
- **Buys BOTH sides of the same bar** (33 of 47 in-sample markets two-sided), and
  buys **cheap**: BUY price **median 0.26** (p10 0.09, p90 0.78) — heavily skewed to
  the *underpriced tail*.
- Clean example — Solana 10:50 bar: UP 65.8sh@0.321 **+** DOWN 82.7sh@0.173, total
  cost **$35.5**; whichever side wins pays **≥$65.8** → locked ~$30+ regardless of
  outcome.

**The edge:** these 5m markets **overshoot**. When the underlying ticks one way
mid-bar, panic sellers dump the trailing side to 0.03–0.15 — but 5-minute crypto
reverses often, so that tail is worth more than its price. He is the **liquidity
buyer picking off the overshoot**, accumulating the cheap side(s) until his total
cost sits below the guaranteed winning payout. Not every market locks (≈20/33 had
combined cost < payout; some he overpays chasing) — but the cheap-tail buys dominate,
giving a durable +EV that compounds. It's HFT-style liquidity provision *by taking*,
not passive quoting.

## Why this matters for US (direct)
This is the **mirror image of our cur2 bot's problem**, in the *same markets*:
- Our bot **rests at 0.50 and gets adversely selected** — it's the passive maker that
  informed flow runs over.
- @thierrax1 is the **aggressor on the other side** — he profits from exactly the
  mid-bar overshoot/mispricing our bot loses to.
- ⚠️ **This kills the naive mid-bar stop-loss** from `CUR2_STOPLOSS_ANALYSIS.md`:
  if we market-sell a losing position at 0.05 mid-bar, **he is the counterparty
  buying it** — i.e. our "stop" is us being the panic seller he feeds on. Our exit
  price would be adverse. Reinforces: **pre-trade gates > in-flight stop-loss.**

## Can we replicate it? (open question — not decided)
Plausibly yes, and it's in markets we already have plumbing for. Requirements:
1. **Live orderbook feed** on the crypto 5m UpDown markets (all coins) + a fair-value
   model: how cheap is "too cheap" given time-left-in-bar and the size of the move.
2. **Fast taker execution** — buy the tail within seconds of the dump, across many
   markets in parallel. (Opposite of our current rest-at-0.50 design.)
3. **Bankroll + compounding risk mgmt** — he grows size with equity, keeps DD ~7%.
The core bet is "5m UpDown markets overshoot the true reversal probability." Next step
if we pursue: record live book depth + tail prices vs realized reversal rate on a
sample of bars to measure the edge before building.

---

## MEASURED (2026-07-11) — the "overshoot / cheap-tail" edge does NOT exist
Method: 750 resolved bars × 5 coins (SOL/BTC/ETH/XRP/DOGE), CLOB 1-min token-price
marks sampled at each in-bar minute → **6,000 (price, won?) observations**; calibrate
realized win% vs price. (`scratchpad/overshoot/`, collect.py + analyze.py.)

**Result — the markets are efficiently priced at minute granularity:**

| mark price | realized win% | 95% CI | verdict |
|---|---|---|---|
| 0.06 | 3.1% | [1,9]% | slightly OVER-priced |
| 0.10 | 7.4% | [4,13]% | over-priced (buy loses) |
| 0.15 | 8.8% | [5,14]% | over-priced (−0.06) |
| 0.30 | 27.6% | [24,32]% | ≈fair / slightly over |
| 0.44 | 44.3% | [42,47]% | fair |
| 0.73 | 73.1% | [70,76]% | fair |
| **0.90** | **93.7%** | **[91,95]%** | **UNDER-priced, +3.5% — the ONLY statistically +EV bucket** |

- **The cheap tail is fair-to-slightly-OVERpriced** — buying the overshot longshot and
  holding is −EV. The hypothesized overshoot edge is **falsified**.
- **The only real static edge is the mirror image: FAVORITES are slightly underpriced.**
  Buy the ~0.90 side → wins ~94% (CI entirely above 0.90). +3.5% gross, thin.
- This matches @thierrax1's **own fills**: his cheap-longshot buys LOSE (0.14 fills win
  1%); his money is in favorite buys — 0.55–0.80 fills won **95.9%** (+27% vs price),
  0.90 fills won 100%. He buys the **near-locked winner**, not the cheap tail.

## Revised conclusion — what his edge really is
Not a passive mispricing anyone can harvest. It's **timing/latency on the favorite
side**: buy the side once the bar's move is nearly decided but the book still lags
its true (near-1) probability, at massive volume, compounding. The +3.5% static
favorite edge is the floor; his +27% on 0.55–0.80 fills is *moment selection* on top.

**Replicability for us:** the passive version is dead (no cheap-tail edge; favorite
edge too thin after buying at the ask + fees). A real attempt needs a **taker bot with
a live orderbook feed + a "near-locked favorite the book hasn't caught up to" detector
+ sub-second execution** — the opposite of our rest-at-0.50 design, and a real build.
Our current infra cannot capture it. Recommend **not** chasing this without that
execution stack; the measured static edge doesn't justify a passive strategy.
