# Intra-bar MM flipping (buy 50¢ / sell 51¢, repeat). VERDICT: DEAD — momentum books.

User idea 2026-08-13 ("trade frequently instead of waiting for resolution").
Sim `scratchpad kl/pf_bt_mm.py` on real 1h recordings (88 bars): rest
BUY at mid−X and SELL at mid+X on the UP token, inventory 0..50sh,
round-trips capture 2X, residual settles at outcome.

| half-spread X | round-trips/bar | net/bar |
|---|---|---|
| 1¢ | 23.2 | **−$0.65** |
| 2¢ | 5.6 | **−$0.85** |
| 2¢ + 0.5¢/sh rebate credit | 5.6 | −$0.07 |
| 3¢ | 2.6 | +$0.09 (noise) |
| (pair-and-hold, same data) | 1 | **+$1.00** |

More flipping = more loss: your buy fills when price is FALLING (momentum
continues to 49, 48...), the sell at 51 never comes, worst bars −$49..−$67.
Consistent with the July finding (intrabar MOMENTUM not reversion,
rebate-harvest-dead). "More frequent" must come from MORE BARS (shorter
series, more coins) or batch pairs — never from intra-bar flips.
