# every-tick-trader — Polymarket maker-rebate quoting bot

Per-coin instances: `btc-every-tick-trader`, `eth-every-tick-trader`, … Source ported from
`polymarket/k8s/helm/polymarket-btc-5m-bot` (the math_smart 5m taker bot); this project flips
the role: **be the maker, not the taker** — quote every 5m tick, collect spread + maker rebates.

## 1. The rebate program (verified from Polymarket docs, 2026-07)

- Takers pay a category fee; **crypto = feeRate 0.07** (highest; ~1.8%/100 shares cap).
  Makers pay nothing.
- **20% of crypto taker fees** go to a daily maker-rebate pool, split **per market**,
  proportional to each maker's filled-order weight:
  `fee_equivalent = shares × feeRate × p × (1−p)`
- **p(1−p) peaks at p=0.50** → a fill at 50c carries 0.25 weight vs 0.09 at 90c — **~2.8×
  more rebate weight near 50c**. This is the "more rebates near 50c" effect (it's the weight
  formula, not a separate bonus).
- Paid daily in pUSD, min $1 accrued. Only FILLED maker orders count.

## 2. Why this can be profitable (and what kills it)

Three PnL streams per bar:
1. **Two-sided lock:** bid UP at `b_u` and DOWN at `b_d` with `b_u + b_d < 1`. If BOTH fill,
   the pair settles at exactly $1 → locked profit `1 − (b_u + b_d)` regardless of outcome.
2. **Rebates** on every filled quote (max weight near 50c — exactly where a 5m bar opens).
3. **Spread capture** on one-sided fills that mean-revert.

### 2b. v1 live mode: ONE-SIDED hold-to-expiry (current)

Rest a single bid per bar (`QUOTE_MODE=one_sided`, side=`cheaper` — the ≤50c side, max
p(1−p) rebate weight, least $ at risk), hold any fill to expiry. The math:
**EV per share = q − p** (q = the fills' realized win rate, p = fill price). If fills are
unbiased (q ≈ p), directional PnL ≈ 0 and **rebates are pure profit**. The rebate is at most
~0.35c/share at 50c (20% × 0.07 × 0.25, assuming the whole pool), so the strategy survives
only if adverse selection keeps q within ~0.7pp of p. Paper logs measure exactly this:
q-vs-p per price bucket from `paper_fill` + `paper_bar_settle` events.

**Backlog:** A/B the `two_sided` pair-lock mode (quote both tokens, both-fill locks
1−(b_u+b_d) risk-free) against one-sided — e.g. run 2 coins per mode over the same week and
compare net PnL after adverse selection. The two-sided code is implemented and config-gated.

The killer: **adverse selection late in the bar** — informed flow (our own old math_smart bot
was exactly this taker!) hits stale quotes when the BTC move is already known. Mitigations
are the core of the strategy:
- **Quote early** (first minutes, p≈50c: max rebate weight, flow is mostly uninformed).
- **Hard cutoff**: cancel all quotes at T−`quoteCutoffSecs` (default 60s) — never rest quotes
  in the sniping window.
- **Reprice on movement**: cancel/replace when BTC moves > z threshold (reuse the bot's
  z/sigma machinery) so quotes never go stale mid-bar.
- **Inventory cap** per bar per coin; filled inventory holds to expiry (5m settle) in v1.

## 3. Paper mode (this phase)

No real orders. A paper engine simulates our resting quotes against the LIVE book/trade feed:
- Our bid at P fills when the market prints a trade at ≤ P (or the book crosses our level),
  fill size capped by printed size. Conservative by design.
- Settlement at bar expiry using the actual outcome.
- Logs (jsonl, same pipeline as before): quote lifecycle, paper fills (with fee_equivalent),
  bar settles (PnL split: two-sided lock / directional / rebate est.), daily rebate estimate.
- **All available 5m coins** (BTC/ETH/SOL/XRP per gamma discovery) for maximal log volume.

Rebate estimate honesty: the actual rebate depends on OTHER makers' fee-equivalent in the same
market (proportional split). Paper logs the fee_equivalent numerator; the realized pool share
is only knowable live. Treat paper rebate numbers as upper bounds.

## 4. Success criteria to go live

- ≥1 week of paper across all coins.
- Two-sided fill rate, one-sided adverse-selection loss, and net PnL per bar ≥ 0 **before**
  rebates (rebates then are pure upside), or clearly ≥ 0 after conservative (50%-haircut)
  rebate estimates.
- Live starts tiny ($1–5 quotes) on BTC only.

## 5. Layout

- `src/` — bot source (ported; new: `strategies/maker_rebate.py`, `paper_book.py`)
- `chart/` — helm chart (per-coin values files)
- `Dockerfile`
- research/sweep scripts stay in `chart/` root for now (from the old project)
