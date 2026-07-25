# winner-vacuum — post-close 99c winner vacuum (Polymarket 5m up/down)

**Edge (validated 2026-07-25).** After a 5m bar closes the outcome is decided,
but holders of the *winning* token keep dumping at **0.955–0.999** during the
1–5 min resolution delay to free capital instantly instead of waiting for
redemption. Buying those sells and redeeming at $1.00 is near-riskless.

Evidence:
- Wallet `0xA7614974…` runs exactly this on btc: **172 bars, 100% win rate,
  median fill +9s post-close at 0.99, +$26.5k / 115 days**.
- Our own trade-tape measurement (541 btc bars): post-close winner-token buys
  at 0.955–0.999 average **~$8.5/bar of riskless edge**; 21% of bars carry
  >100 shares of supply; the best bars pay ~$700.

**Mechanics.** Same GTC-REST pattern as `settlement-sniper` (FAK spray is
latency-doomed; a presigned resting bid is matched server-side with zero
per-fill latency):

1. Pre-close: track `lead = (spot − open)/open` from the Binance WS feed.
2. At close: lock winner = UP if lead>0 else DOWN; **skip if |lead| < 8bps**
   (a mislock costs ~0.99/share here — the near-tie gate is the whole risk
   control; measured 0 lock errors at |lead|≥5bps).
3. Post one **presigned GTC buy at 0.99** on the winner. Resting asks below
   0.99 fill immediately at their (cheaper) price; later capital-freers cross
   into us server-side.
4. Cancel the unfilled remainder at +20s; hold fills; redeem at settlement.

**Economics.** Edge ≥ ~1c/share (more when sellers sit at 0.96–0.98). At
$100/deal ≈ 101 shares, a filled bar nets ~$1+; supply-rich bars considerably
more. Taker fee at p=0.99 is ~0.07·0.99·0.01 ≈ negligible.

**Layout.** `src/vacuum.py` + symlinks into `pm-common/execution` (TakerRunner/
FastExec) and `every-tick-single/src` (core/engine/config). Chart is a copy of
the settlement-sniper chart (same `SNIPE_*` env keys, entrypoint `vacuum.py`).

**Deploy** (defaults are PAPER; live needs the creds overlay):

    source ../.dev-env-source
    ./deploy.sh btc paper     # dry-run mechanics
    ./deploy.sh btc live      # real money — sizing in chart/bots/btc_vacuum.yaml

Key knobs (chart/bots/btc_vacuum.yaml): `snipeCap` 0.99, `snipeFireMaxSecs` 20,
`snipeNotional` 100 ($/deal), `snipeMinLeadBps` 8, `snipeMaxDailyLoss` 100,
`postCloseGraceSecs` 25.
