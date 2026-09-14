# Sweep quality across 7 coins and 30 days — from the pod ledger alone
**2026-09-14. No fill model, no tape, no replay. Nothing deployed.**

Provoked by four bar autopsies that all pointed at the same object (a dollar-FAK sweeping a
collapsing book) with opposite signs. Four bars cannot settle it. The **ledger** can.

## 0. The surface is much bigger than we have been treating it

`PF_TE_WHALE_ORDER` + `PF_TE_LIVE_SETTLE`, pulled from all 7 vacmaker pods:

| | |
|---|---|
| fires logged | **8,487** (archives start 08-16, ~30 days) |
| joined to a settle with real PnL | **4,384 fills** |
| net, **fee-charged** | **+$241.29** ≈ **$8/day** |
| win rate | 96.6% |

⭐ That $8/day independently reproduces [[fleet-baseline-corrected]] from a different join. And it
needs **no market tape at all** — every field used below is already in the event.

⚠️ **The tape is the scarce thing, not the ledger.** The recorder pods carry **0 rolled hours** —
`archive_mrec.sh` drains them every 30 min — so the only mrec that exists is what is local:
**09-12 → 09-14, three days**. Anything needing bid history, spot or Binance at fire time is capped
there and only grows forward. Anything answerable from ledger fields has **30 days**.

## 1. ⛔ Near-threshold fires are NOT worse (a clean negative)

Three of the four autopsied bars cleared `eff_thresh = 0.5 + 0.035·max(0, tl−14)` by **under
0.01 bps**, which looked alarming. Measured on all 4,384 fills:

| `|est| − gate` | n | win% | net | $/fill |
|---|---|---|---|---|
| **0.00 – 0.05** | 670 | 96.3% | +$68.61 | **+0.102** |
| 0.05 – 0.20 | 813 | 95.9% | +$80.05 | +0.098 |
| 0.20 – 0.50 | 920 | 96.7% | +$0.58 | +0.001 |
| 0.50 – 1.50 | 1279 | 97.3% | +$90.76 | +0.071 |
| ≥ 1.50 | 548 | 96.5% | +$32.53 | +0.059 |

Razor-thin fires are the **best** bucket per fill. **Closed — do not propose a conviction floor.**

## 2. ⭐ Sweep quality is about the ask you swept FROM, and it survives scrutiny

Split the 4,384 fills by how far below the displayed ask we actually filled:

| displayed − fill | n | win% | net | $/fill | % of net |
|---|---|---|---|---|---|
| ~0 (at display) | 4,090 | 97.5% | +$133.40 | +0.033 | 55% |
| 0.5–5c | 194 | 91.8% | +$67.23 | +0.347 | 28% |
| 5–15c | 61 | 78.7% | +$13.48 | +0.221 | 6% |
| 15–30c | 26 | 50.0% | **−$48.09** | −1.849 | −20% |
| ≥30c | 13 | 53.8% | +$75.26 | +5.789 | 31% |

Depth alone is not the variable — the 15-30c and ≥30c buckets have the same win rate and opposite
sign. Now split the **deep sweeps (≥5c)** by the ask they swept from:

| swept from | n | win% | net | $/fill | ex-best | days +/total |
|---|---|---|---|---|---|---|
| **≥ 0.98** | 32 | **84.4%** | **+$103.08** | **+3.221** | **+$28.26** | **16 / 20** |
| 0.80 – 0.98 | 45 | 64.4% | −$76.22 | −1.694 | −$96.20 | 11 / 21 |
| < 0.80 | 23 | 52.2% | +$13.79 | +0.600 | −$17.48 | 8 / 16 |

**The ≥0.98 deep sweep is the business.** It survives dropping its single best fill (+$28.26 still)
and is positive on 16 of 20 days it occurs. This extends [[btc-live-fill-ledger]]'s btc-only result
(188 fills, ≥0.98 sweeps +$37.46) to **7 coins and 30 days** — same sign, same shape, 32 fills.

## 3. ⛔ …but the "0.80–0.98 trap band" is ONE DAY. Do not use it.

The −$76.22 looks like a clean veto target, and 6 of 7 coins are negative. It is not:

```
per day: 08-17 −5  08-19 −8  08-20 −5  08-21 +6  08-22 −4  08-23 −21  08-24 +5
         08-25 −7  08-26 +7  08-27 +2  08-28 +6  08-29 +4  09-03 −24  09-04 −22
         09-05 +6  09-06 +10 09-07 −4  09-08 +20 09-09 −70  09-10 +13 09-14 +14
```

**09-09 alone is −$70 of the −$76.** Ex-09-09 the band is ≈ **−$6 over 44 fills (−$0.14/fill)** —
noise. 09-09 is the already-known −$66.93 (95-7) day; this "finding" mostly re-describes it. The
[[vacmaker-analytics-leads]] single-day fingerprint again (§45-47, and the zec cheap cell).

⚠️ The four autopsied bars sit in this picture exactly where the bands say: bnb swept from 0.99
(+$9.06, the ≥0.98 class); btc 13:40 from 0.79 and btc 09-12 from 0.67 (**both in the <0.80 band,
one +$30.10 and one −$20.80** — a 52%-win, near-zero-aggregate class, which is precisely why no
signal at the fire distinguished them).

## 4. Concentration, restated

Top **5** fills = **$195.20 = 81%** of the 30-day net. Top 20 = $354.41 = 147% (i.e. the rest is
net negative). Worst 5 = −$122.48. Nothing here changes [[fleet-baseline-corrected]]: this is a
business of a handful of windfalls, and any candidate that does not touch them is rounding error.

## 5. Reproduce

```bash
for c in btc eth sol xrp bnb doge hype; do
  kubectl exec -n every-tick-single deploy/$c-vacmaker-every-tick-single -- sh -c \
   '{ zcat /app/logs/*.gz 2>/dev/null; cat /app/logs/logs-training-events.jsonl; } |
    grep -E "PF_TE_WHALE_ORDER|PF_TE_LIVE_SETTLE"' > led/$c.jsonl
done
```
Join on `(coin, bar, clip)`; charge `fee = sh·0.07·px·(1−px)` — the ledger does not.
