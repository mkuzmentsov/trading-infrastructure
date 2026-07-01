# Prompt 2 — Open / rotate (EXECUTES, confirm-gated)

Two passes: PLAN (dry-run) then EXECUTE on "confirm". Be concise: show the plan as a short
checklist + fee/basis math, no narration. Start with today's UTC date; end with a one-line
dated position summary.

---

Using the `trading` MCP, open a funding-carry (rotating out of any existing one first), delta-
neutral and fee-aware. PLAN first (dry-run); EXECUTE only after I reply "confirm". Be short.

TARGET: <coin> short on <venue>, long spot on <venue>, flex earn on the long leg.
(Blank = pick the highest combined funding+earn per compare_perp_funding +
find_best_yield_anywhere; state the pick before executing.)

0. PRE-FLIGHT: hyperliquid_get_accounts_overview — confirm collateral is on the TRADING sub
   (deposits land on the master; transfer master→sub if needed). Confirm long-leg USDT is on the
   long venue's spot wallet, and any key has the perms the plan needs (Kraken "Withdraw Funds").

1. CLOSE existing (if any, and ≠ target): deallocate earn FIRST (flex, poll till freed) →
   close short → sell spot. Verify flat.

2. REBALANCE stables (only if drifted): read USDT/USDC per venue; compute the split the new
   position needs (short margin on short venue, spot capital on long venue). BEFORE transferring,
   price withdrawal/network fees (kraken_get_deposit_methods, whitebit_get_fee_schedule,
   binance deposit networks, hyperliquid_get_deposit_info) + get the deposit address. Move only
   if benefit (extra deployable × APR over 30d) > fee; else size to the current split. Show the math.

3. OPEN — entry-basis gated. Call carry_basis(coin, notional, short_venue, long_venue) for the
   real order-book taker/maker basis + depth. Gate (funding-relative — the entry cost must pay
   back fast): open on TAKER if taker_basis_bps ≥ −(funding_apr/365 × 7 days in bps) — for a ~11%
   carry that's ~−21 bps, but prefer ≥ −5 (near-flat). If only maker passes, post a maker BUY at
   the bid then instantly taker-short once it fills. If neither passes or depth can't absorb the
   size, re-quote or switch to a tighter-tick / deeper coin (coarse-tick $-cheap coins like ENA
   enter poorly on taker — a $0.07 coin's 1 tick = ~14 bps). Execute both back-to-back,
   quantity-matched — NOTE Binance charges the spot fee IN THE COIN, so short the NET filled qty,
   not the ordered qty. Reconcile realized basis; if a leg fills but its hedge doesn't, unwind —
   never sit naked. Then (only if the long leg is a stablecoin or has real allocatable earn)
   subscribe it to FLEX earn — alt long legs earn ~0, skip.

4. REPORT (one line): date | coin | short venue+size+funding | spot venue+size | earn venue+APY |
   realized basis_bps | combined APR | fees | resulting per-venue stable balances.

GUARDRAILS: dry-run every order/transfer; execute on confirm only. Earn = FLEX (instant unstake).
Never open through an unfavorable basis (perp_sell < spot_buy by >5 bps). Never sit on a naked leg.
