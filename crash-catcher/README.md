# crash-catcher — both-side 1c catch-bids (Polymarket 5m up/down)

**Edge (validated 2026-07-25).** Late panic-dumps on a "dying" side overshoot:
tokens swept to $0.01 still win ~4–5% of bars, so a 1c fill has
EV ≈ 0.04·$0.99 − 0.96·$0.01 ≈ **+3c/share**. Live proof: wallet
`0xCd9bf7F6…` — 115 days, 1,492 bars filled at median $0.01, 5% winners,
+$22k (~$190/day). Our recorder tape: 1c-zone fills win 3.4–4.1%.

**Mechanics.**
1. At bar open, place presigned **GTC bids at $0.01 on BOTH tokens**
   (5 shares each — venue minimum for resting limits; $0.05/side).
   Early placement = front of the FIFO queue at the 1c level — the moat.
2. Most bars: nothing fills, orders cancelled.
3. **Cancel strictly ~0.7s BEFORE close** — post-close the losing token goes
   to 0 and a lingering 1c bid is a guaranteed donation.
4. Fills are held to settlement; winners redeem $1.00 (100×).

Kill-switch: daily realized loss cap (`CATCH_MAX_DAILY_LOSS`). The failure
mode is slow bleed (1c/share on ~96% of fills) if the flip rate decays —
watch trailing fill win-rate before scaling shares.

**Paper mode caveat:** resting-bid fills cannot be simulated honestly by the
paper exec, so paper mode counts live trade prints at ≤ $0.01 while the bid
would be active — a FRONT-OF-QUEUE OPTIMISTIC upper bound, labeled
`CATCH_PAPER_PRINT`/`CATCH_FILL live=False`. Only live measures real queue share.

**Layout/deploy:** same skeleton as `winner-vacuum` (symlinks into
`pm-common/execution` + `every-tick-single/src`; chart copied from
settlement-sniper with `CATCH_*` env keys added to the secret template).

    source ../.dev-env-source
    ./deploy.sh btc paper
    ./deploy.sh btc live   # real money — 5 shares/side, $5/day loss cap

Sources for the venue minimum (resting GTC = 5 shares; $1 notional applies
only to marketable orders): https://github.com/Polymarket/py-clob-client/issues/301,
https://polymarkets.co.il/en/api/polymarket-api-errors/
