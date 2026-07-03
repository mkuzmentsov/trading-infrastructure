# every-tick-single — single-side maker experiment (PAPER)

Fork of `every-tick-both/` (ex `every-tick-trader/`) (2026-07-03) so single-side experiments never touch
the LIVE two-sided btc bot. This project: 4 paper bots (btc/eth/sol/xrp),
bracket mode, `BRACKET_SIDES=one`, fixed post-only entry at ~0.48, no stop,
hold to expiry. Namespace: `every-tick-single`.

Deploy: `cd <repo root> && source .dev-env-source && ./deploy.sh [coin ...]`

Findings log + strategy rationale: see `every-tick-both/PLAN.md` (shared history).
Current open question: single-side win rate ~44% vs 48% breakeven, side picker
degenerate (always UP) — candidates: bet-against-previous-bar (GM finding),
or retire single-side if two-sided + pair-incomplete-exit wins.
