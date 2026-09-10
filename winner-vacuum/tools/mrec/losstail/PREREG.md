# PRE-REGISTRATION — Agent A loss-tail veto, 2026-09-10 (written BEFORE looking at any result)

## Fill cell (fixed in advance)
House cell, bug #27: fill window 0.4s FORWARD, price improvement 0c (fill AT displayed ask),
size walked down displayed top-3 ask ladder, tape-confirmed BUY print at px<=limit,
CLIP=$24 / LADDER=$48, GAP=8s. Live gates: tlk in [3,20], cov>=0.5,
|est| >= 0.10+0.035*max(0,tl-14), ask in [0.55,0.99], first-clip skip 0.90-0.98, ladder floor 0.94.
Secondary cell for robustness: same + tape-size cap (bug #28). Loss COUNTS are the primary metric,
$/day is fill-model dependent and reported only as a range.

## Hypotheses
H1 (bid drop). Among fired clips, a fall in the favourite's own best bid over the prior K s
(K in 5,6,10,20; absolute dB and relative rB) predicts a losing clip.
H2 (thin estimate). |est_bps| - threshold (margin over the fire threshold) predicts a losing clip.
H3 (which carries it). In a joint bar-clustered logit with both terms + interaction, at most one
survives; the surviving term is the variable a veto should key on (the §37 lesson).

## Decision rules (fixed in advance)
- Full-sample: report loss-rate lift, bar-clustered SE, and the coefficient signs.
- STRICT OOS: fit/choose threshold on bars with day <= 2026-09-07; freeze; evaluate on
  2026-09-08..09-10 only. OOS is the headline.
- LOO by day and by coin on the OOS-frozen rule; report the WORST fold.
- SHIP iff: OOS loss-bars/day falls >=50%, OOS net $/day >= 0 in BOTH fill cells, AND no
  LOO-by-day fold flips the loss-count sign.
- LOG-ONLY ARM iff: full-sample separation holds and OOS direction agrees but OOS is
  underpowered (fewer than ~8 OOS losing clips) or $/day ambiguous.
- REFUTED iff: OOS shows no separation (loss-rate lift <1.2x) or the effect is carried by a
  single day/coin in LOO.
