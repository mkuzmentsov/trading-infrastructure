# Momentum-taker (buy the forming favorite at ask, hold to settle). VERDICT: ⛔ DEAD all bands all coins (pooled 2026-08-15).

## Why re-opened
July's "fav-taker net-negative" verdict used the old ~10% fee formula. The
current `crypto_fees_v2` fee = 0.07·p(1−p) ≈ **0.5¢/share at p=0.92** — an
~8.8¢/share cost reduction exactly where favorite-taking lives. The kill did
not automatically transfer.

## Test design (honest timing, no look-ahead)
5m post-TWAP mrec raw, 7d btc. Sample moments tl∈{240..60}s; enter a side
ONCE per bar when its ask rose ≥2¢ vs 30s earlier (momentum confirm, uses
only past snaps); buy AT the ask; hold to settlement; fee charged exactly;
wins from RES rows.

## Results (btc, 7d, 2026-08-15 ~01:00)
| entry band | n | win% | hurdle ≈ask+fee | PnL/share | verdict |
|---|---|---|---|---|---|
| 0.60-0.70 | 1,089 | 64.6% | ~65.5% | −1.14¢ | ⛔ dead |
| 0.70-0.80 | 818 | 73.6% | ~75.5% | −2.06¢ | ⛔ dead |
| 0.80-0.90 | 539 | 81.1% | ~85.5% | −3.62¢ | ⛔ dead (worst) |
| **0.90-0.96** | **129** | **94.6%** | **~93.0%** | **+1.81¢** | 🔍 CI includes loss (94.6±3.9 → lower 90.7 < hurdle) |

Mid-bands: favorites remain over-priced even at cheap fees — the informed-
flow premium exceeds the fee saving. The ≥0.90 pocket matches the July
"fav pocket" intuition (FAV_* gates already exist in the chart/config).

## FINAL: pooled verdict (2026-08-15 ~01:40)
0.90-0.96 band across 5 more coins: eth −2.4¢/sh (n=1,140, 90.4%), sol
−0.8¢ (1,123, 92.0%), xrp −0.9¢ (1,220, 92.0%), doge −5.1¢ (1,242, 87.9%),
bnb −3.9¢ (1,198, 89.1%). ALL negative; btc's +1.8¢ (n=129) was the
small-sample fluke its own CI flagged. **⛔ mid-bar momentum-taking is dead
at every price on every coin even under crypto_fees_v2** — the favorite's
informed premium exceeds the fee saving everywhere. The taker cell that DOES
work is the T−14s TWAP-implied entry (see ../VACMAKER.md — different signal:
settlement reconstruction, not price momentum; different timing: inside the
TWAP window, not mid-bar).

## Also closed same night: 1h/1d late-window taker
Signal perfect (flip 0.00% ≥3bps at t≤30s, Binance-settled) but no supply:
winner-asks ≤0.98 in 4-7% of bars, ~$1.2/day capturable (7d measured).
Hourly closes are swept like 5m ones.
