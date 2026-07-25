---
name: pm-scout
description: Scan ALL Polymarket markets, review the wallet's positions/redemptions, research world situation, and produce a ranked bet list with allocation for a user-specified bankroll. Use when the user says "/pm-scout <amount>", "scan polymarket", or asks what to bet on Polymarket. Analysis-first; orders ONLY after explicit user approval.
---

# pm-scout — Polymarket scan → analyze → review → execute

Module: `pm-scout/` (tools + `KNOWLEDGE.md`). Wallet = the tail-bot Safe
(creds overlay `every-tick-single/chart/bots/sol.secret.yaml`). The `<amount>`
argument is the bankroll to allocate THIS run (independent of wallet total).

## Hard rules
- **Read `pm-scout/KNOWLEDGE.md` FIRST, fully.** All standing verdicts apply
  (crypto 5m/15m UpDown are proven efficient — never list them on price alone).
- **No order without explicit user approval of that specific action** in this
  conversation. `place.py` refuses without `--confirm`.
- If a position already exists in a market: never a new independent bet — only
  HOLD / CLOSE / INCREASE in the portfolio section.
- Newest markets take precedence. Every bet line shows resolution timing.

## Run steps
1. `cd pm-scout`
2. **Portfolio first**: `python3 tools/wallet.py` →
   - redeemables worth claiming → propose `place.py redeem`
   - each open position: re-check the market's current situation (step 4 style)
     → recommend HOLD / CLOSE / INCREASE with 1-2 line reasoning.
3. **Scan**: `python3 tools/scan.py --digest --max-pages 40` (full JSON lands in
   `runs/scan-<ts>.json`). Triage to ~10-20 candidates: newest first, then
   rewards-carrying, closing-soon with stale-looking prices, top-volume movers.
   All categories incl. sports. Load candidate details from the scan JSON
   (description, resolutionSource, endDate, negRisk, fees).
4. **Analyze each candidate** (best effort, honest):
   - read the resolution rules (description/resolutionSource) — exact terms!
   - `python3 tools/flow.py <conditionId>` — whale/insider prints: big one-sided
     entry = follow-signal; big dump against a held side = close-warning.
   - research the world situation: WebSearch news/polls/data/schedules.
   - estimate true probability BEFORE anchoring on price; state confidence.
   - `python3 tools/book.py <token> --size <planned>` — depth check.
   - net edge = est_prob − ask − fees (crypto up/down taker only; makers free).
5. **Report** (single reviewable message):
   - redemptions → position actions → ranked new bets
   - per bet: market | side | price → est.prob (confidence) | net edge |
     resolves-when + capital-lock days | edge/day | WHY (2-3 lines) |
     what kills it | maker or taker entry | $ allocation
   - allocation: edge-and-confidence weighted, ≤20%/bet, ~20% reserve; prefer
     sooner resolutions (edge per locked day); note rewards/rebate income.
6. **Execute after approval** (each approved line):
   - `python3 tools/place.py bet --token T --price P --shares N --thesis "..." --confirm`
     (maker post-only GTC default; `--taker` only if time-critical)
   - closes/increases via `place.py close` / `bet`; redemptions via `place.py redeem --confirm`
   - verify resting orders / fills; report back.
7. **Record**: write `pm-scout/runs/run-<ts>.md` (shortlist, theses, est.probs,
   actions taken). Actions auto-append to `runs/ledger.jsonl`.
8. **Learn**: check previous runs' bets for resolutions; append outcomes to the
   calibration ledger in KNOWLEDGE.md + any transferable lesson. This step is
   MANDATORY — the module's edge compounds through it.
