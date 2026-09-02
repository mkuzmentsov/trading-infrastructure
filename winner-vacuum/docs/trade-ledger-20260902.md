# Vacmaker trade ledger — UTC day 2026-09-02 (through ~11:55 UTC)

## Context for the investigating agent
Strategy: taker "whale clone" on Polymarket 5m/15m Up-Down markets. It
reconstructs the Chainlink TWAP-60 settlement value in real time and buys the
implied winner's ask in the final ~20s of each bar (fires when the
reconstructed margin |est| clears a threshold ≈0.5-0.7bps and the ask is in
band [0.55, 0.98/0.99]). Clips are $24 FAK orders (dollar-capped: price
improvement yields more shares). Ladder = up to $48/bar, but a 2nd clip may
only fire ≥8s after the 1st and must re-qualify on fresh state (§61).
Protections: mid-band opening-clip skip 0.90-0.98 (§58, eth exempt); "toxic
brake" — if a fill lands ≥5% below the displayed ask (stale quote into a
dump), no more clips that bar (§59); loss halts = 1h cooldown per extra $30
of day loss (§57), except xrp where halts are disabled by user.
Loss classes to distinguish when investigating:
 A) decisive-flip: honest fill at 0.94-0.99, margin decent, bar flips late.
    Irreducible; §61 caps it to one clip.
 B) thin-est + cheap-fill: margin barely over threshold AND fill far below
    displayed ask — the market disagreed and was right (brake targets these).
 C) windfall: same cheap-fill signature but OUR side wins — huge ROI.
Baseline: ~96-99% of bars win small (+0.2-0.5/clip); a loss costs a full
clip ($19-24). Question worth investigating: any common structure in today's
6 loss bars beyond the known classes (time clustering, cross-coin
correlation, order-book state)?

## Trades (49 settled bars)

| # | UTC | coin | side→won | clips | staked | PnL | flags | entries |
|---|---|---|---|---|---|---|---|---|
| 1 | 23:50 | hype | UP→UP | 2 | $27.98 | +1.17 | - | n/a |
| 2 | 23:55 | eth | DOWN→DOWN | 1 | $23.76 | +0.24 | - | n/a |
| 3 | 00:00 | btc | UP→UP | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=0.853bps tl=20.0s |
| 4 | 00:00 | xrp | UP→UP | 1 | $2.37 | +0.02 | - | clip1 @0.99 est=1.202bps tl=20.0s |
| 5 | 00:10 | xrp | UP→UP | 1 | $23.76 | +0.31 | - | clip1 @0.98 est=1.331bps tl=20.0s |
| 6 | 00:15 | doge | DOWN→DOWN | 1 | $22.58 | +0.36 | - | clip1 @0.98 est=-0.973bps tl=19.9s |
| 7 | 00:20 | btc | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-0.755bps tl=20.0s |
| 8 | 00:30 | eth | UP→DOWN | 1 | $9.28 | -9.28 | LOSS | clip1 @0.68 (filled 0.650, 4% below ask) est=0.863bps tl=19.6s |
| 9 | 00:45 | eth | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-1.5bps tl=20.0s |
| 10 | 00:45 | sol | UP→UP | 1 | $21.93 | +0.22 | - | clip1 @0.99 est=1.498bps tl=20.0s |
| 11 | 00:55 | eth | UP→UP | 1 | $23.76 | +0.39 | - | clip1 @0.98 est=1.247bps tl=20.0s |
| 12 | 01:00 | btc | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-0.923bps tl=18.6s |
| 13 | 01:00 | doge | DOWN→DOWN | 1 | $17.82 | +0.18 | - | clip1 @0.99 est=-0.937bps tl=19.9s |
| 14 | 01:00 | eth | UP→UP | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=1.156bps tl=19.9s |
| 15 | 01:00 | hype | UP→UP | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=2.956bps tl=20.0s |
| 16 | 01:00 | sol | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-0.787bps tl=19.9s |
| 17 | 01:05 | sol | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-1.042bps tl=19.9s |
| 18 | 01:05 | xrp | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-0.841bps tl=20.0s |
| 19 | 01:15 | bnb | DOWN→DOWN | 1 | $21.76 | +0.22 | - | clip1 @0.99 est=-1.467bps tl=20.0s |
| 20 | 01:15 | xrp | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-2.306bps tl=20.0s |
| 21 | 05:35 | hype | UP→UP | 1 | $21.90 | +0.34 | - | clip1 @0.98 est=1.205bps tl=18.6s |
| 22 | 05:35 | sol | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-1.28bps tl=19.9s |
| 23 | 05:40 | doge | UP→UP | 1 | $6.37 | +0.06 | - | clip1 @0.99 est=1.395bps tl=20.0s |
| 24 | 05:40 | xrp | UP→UP | 1 | $23.76 | +0.24 | - | clip1 @0.98 est=0.892bps tl=15.0s |
| 25 | 06:00 | eth | UP→DOWN | 1 | $23.76 | -23.76 | LOSS | clip1 @0.98 est=0.735bps tl=19.9s |
| 26 | 06:05 | bnb | DOWN→DOWN | 1 | $9.53 | +0.10 | - | clip1 @0.99 est=-0.812bps tl=20.0s |
| 27 | 06:45 | sol | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-0.817bps tl=19.7s |
| 28 | 07:05 | hype | UP→UP | 1 | $23.76 | +0.41 | - | clip1 @0.98 est=1.558bps tl=17.9s |
| 29 | 08:00 | btc | DOWN→DOWN | 1 | $23.76 | +1.52 | - | clip1 @0.98 (filled 0.940, 4% below ask) est=-0.818bps tl=19.9s |
| 30 | 08:00 | sol | DOWN→DOWN | 1 | $23.40 | +3.50 | big-win | clip1 @0.89 (filled 0.870, 2% below ask) est=-1.174bps tl=20.0s |
| 31 | 08:10 | sol | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-1.101bps tl=20.0s |
| 32 | 08:25 | btc | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-0.608bps tl=16.3s |
| 33 | 08:25 | xrp | UP→UP | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=0.509bps tl=13.3s |
| 34 | 08:45 | xrp | UP→UP | 1 | $22.10 | +5.14 | big-win | clip1 @0.84 (filled 0.811, 3% below ask) est=0.665bps tl=15.6s |
| 35 | 09:05 | sol | DOWN→DOWN | 1 | $23.76 | +1.79 | BRAKE | clip1 @0.98 (filled 0.930, 5% below ask) est=-1.815bps tl=6.4s |
| 36 | 09:10 | sol | UP→UP | 1 | $3.90 | +0.04 | - | clip1 @0.99 est=1.746bps tl=19.9s |
| 37 | 09:15 | hype | DOWN→DOWN | 1 | $23.76 | +0.41 | - | clip1 @0.98 est=-1.22bps tl=12.8s |
| 38 | 09:50 | bnb | UP→UP | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=0.729bps tl=19.9s |
| 39 | 09:50 | btc | UP→UP | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=1.391bps tl=19.9s |
| 40 | 09:50 | doge | UP→UP | 1 | $7.77 | +0.08 | - | clip1 @0.99 est=1.157bps tl=13.0s |
| 41 | 10:05 | doge | UP→DOWN | 2 | $28.43 | -28.43 | LOSS | clip1 @0.87 est=0.751bps tl=19.9s; clip2 @0.99 est=0.726bps tl=11.9s |
| 42 | 10:05 | sol | UP→UP | 1 | $14.56 | +27.13 | BRAKE,WINDFALL | clip1 @0.55 (filled 0.349, 36% below ask) est=2.201bps tl=10.9s |
| 43 | 10:10 | btc | DOWN→DOWN | 1 | $23.76 | +0.73 | - | clip1 @0.98 (filled 0.970, 1% below ask) est=-0.636bps tl=17.3s |
| 44 | 10:35 | doge | UP→UP | 1 | $11.63 | +0.12 | - | clip1 @0.99 est=1.791bps tl=20.0s |
| 45 | 10:35 | xrp | UP→UP | 2 | $44.11 | +3.10 | big-win | clip1 @0.89 est=1.147bps tl=19.9s; clip2 @0.99 est=0.963bps tl=11.9s |
| 46 | 11:05 | hype | UP→DOWN | 2 | $25.10 | -14.90 | LOSS | clip1 @0.75 est=0.57bps tl=15.9s; clip2 @0.99 est=-0.699bps tl=7.8s |
| 47 | 11:05 | sol | DOWN→DOWN | 1 | $23.76 | +0.48 | - | clip1 @0.98 est=-1.549bps tl=18.7s |
| 48 | 11:10 | doge | DOWN→UP | 1 | $23.76 | -23.76 | LOSS | clip1 @0.98 est=-2.624bps tl=19.5s |
| 49 | 11:10 | hype | DOWN→DOWN | 1 | $23.76 | +0.24 | - | clip1 @0.99 est=-7.329bps tl=20.0s |

## Narratives (non-routine bars)

- **#8 00:30 eth LOSS -9.28** — bought UP, DOWN won. Class B (thin-est+cheap-fill). Entries: clip1 @0.68 (filled 0.650, 4% below ask) est=0.863bps tl=19.6s. 1 clip(s) — §61 held it to one clip.
- **#25 06:00 eth LOSS -23.76** — bought UP, DOWN won. Class A (decisive-flip). Entries: clip1 @0.98 est=0.735bps tl=19.9s. 1 clip(s) — §61 held it to one clip.
- **#30 08:00 sol big win +3.50** — cheap entry paid: clip1 @0.89 (filled 0.870, 2% below ask) est=-1.174bps tl=20.0s.
- **#34 08:45 xrp big win +5.14** — cheap entry paid: clip1 @0.84 (filled 0.811, 3% below ask) est=0.665bps tl=15.6s.
- **#35 09:05 sol brake trip, won +1.79** — stale-quote fill detected, ladder stopped, kept clip won. Entries: clip1 @0.98 (filled 0.930, 5% below ask) est=-1.815bps tl=6.4s.
- **#41 10:05 doge LOSS -28.43** — bought UP, DOWN won. Class A (decisive-flip). Entries: clip1 @0.87 est=0.751bps tl=19.9s; clip2 @0.99 est=0.726bps tl=11.9s. 2 clip(s) — §61 allowed a re-confirmed ladder clip.
- **#42 10:05 sol WINDFALL +27.13** — class C: clip1 @0.55 (filled 0.349, 36% below ask) est=2.201bps tl=10.9s. Cheap fill kept, pile-on blocked by brake=True.
- **#45 10:35 xrp big win +3.10** — cheap entry paid: clip1 @0.89 est=1.147bps tl=19.9s; clip2 @0.99 est=0.963bps tl=11.9s.
- **#46 11:05 hype LOSS -14.90** — bought UP, DOWN won. Class A (decisive-flip). Entries: clip1 @0.75 est=0.57bps tl=15.9s; clip2 @0.99 est=-0.699bps tl=7.8s. 2 clip(s) — §61 allowed a re-confirmed ladder clip.
- **#48 11:10 doge LOSS -23.76** — bought DOWN, UP won. Class A (decisive-flip). Entries: clip1 @0.98 est=-2.624bps tl=19.5s. 1 clip(s) — §61 held it to one clip.

## Behavioral notes for the investigator
- Bar #46 (hype 11:05): the ladder is side-agnostic per tick — clip1 bought UP
  (est +0.57), by clip2 time the fresh signal read DOWN (est −0.699) and the
  bot bought DOWN@0.99, partially hedging the flip (bar net −14.90 instead of
  ~−25). Legal behavior, not a bug; §61's 8s gap is what made the re-read
  possible.
- Bar #42 (sol 10:05): textbook class-C windfall — MIN_ASK-boundary entry
  displayed 0.55, filled at 0.349 (36% improvement), est decisive 2.2bps,
  brake stopped the ladder, kept clip returned +27.13 (+186% ROI).
- Today's 6 losses: 5×class A (honest decisive-flip, incl. two at est
  0.73-0.75 = barely over threshold) + 1×class B. Open question: 4 of 6
  losses have first-clip est < 0.87bps — is the thin-margin band (0.5-0.9)
  worth a threshold bump? (Prior LOO work on est floors was negative on
  pooled data — re-test on post-§61 data only.)

## Halts today
- 09:54 UTC eth: day_pnl -31.69, episode 1, cooldown 3600s

## Totals: day PnL -45.54 across 49 bars (44W-5L)