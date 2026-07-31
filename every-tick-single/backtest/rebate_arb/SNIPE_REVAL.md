# Settlement-snipe revalidation on 27-30 Jul cache (2026-07-31)

The one edge marked REAL in prior research (leaderboard winners' 79%-of-PnL
mechanism), never harvested by us; `settlement-sniper/` was retired this
morning un-deployed (git history). Re-measured print-exact on 4,860 bars.

## The edge is alive: $1,738/day printed pot (6 coins)

Taker BUY prints on the WINNING token at <=5c AFTER close: $6,952 EV over 4
days. Mechanism confirmed by the event anatomy: LATE-FLIP bars — the side that
looked dead (asks at 1c) wins at the last moment, and its 1c-zone asks from
the dead phase become ~99c/share of free money for whoever sweeps first.

- Lumpy: top-3 events = 62% of the pot; the biggest single bar (btc 07-30
  04:10) printed ~$4.7k across 8 prints at 1-4c.
- Fast but not instant: sweeps start 60ms after close, stragglers fill to
  ~1.3s. Latency capture curve of the pot:
  >=0.1s: 83% | >=0.2s: 46% | >=0.3s: 26% | >=0.5s: 21% | >=1.0s: 14%
- Our measured FAST_EXEC post from Helsinki: 71-243ms -> we contest roughly
  the 26-46% tranche = $450-800/day gross ceiling, before competitors who
  are also in that window take their share. Realistic: low hundreds/day.

## ⚠️ The phantom-book trap (why naive sims of this overstate 4x)

Snapshots at close+0.5s show ~$30k/4d "available" at <=5c on the winner —
but e.g. xrp 07-29 19:00 showed 14,784sh available while only 300sh ever
printed. The venue CULLS resting orders at close (the known
poll_filled-fabricates-fills behavior); our WS book keeps showing culled asks.
PRINTS are the only trustworthy measure. Real pot = $1,738/day, not $7.5k.

## Build shape (= the retired settlement-sniper design, now with numbers)

vacuum-style close-time winner lock (Binance close vs open, min-lead guard
against ties) + presigned FAK sweeps for BOTH tokens at cap ~5c + fire the
winner's at close+~100ms. Failure mode is cheap: buying the loser at <=5c
costs <=5c/share, and a daily halt caps it. Complementary to btc-vacuum
(it SELLS to post-close panic at 0.99; this BUYS stale cheap asks) — same
infra, same lock, opposite books.
