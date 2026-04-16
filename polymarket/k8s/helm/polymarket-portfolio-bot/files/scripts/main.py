#!/usr/bin/env python3
"""
Polymarket Portfolio Bot — entry point.

Each cycle:
  0. Redeem any on-chain positions that already resolved.
  1. Pull USDC balance + live holdings.
  2. Paginate Gamma markets, skipping held + recently-seen ones, until MAX_CANDIDATES.
  3. Fetch news per candidate.
  4. Ask Claude for a unified list of OPEN / ADD / EXIT / HOLD actions.
  5. Execute each action on the CLOB.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

import redemptions
from claude_client import ask_claude, check_anthropic_connection
from clob import ensure_allowances, fetch_usdc_balance, place_buy, place_sell
from config import (
    BET_SIZE_MIN,
    CLAUDE_ENABLED,
    CLAUDE_MODEL,
    DRY_RUN,
    LOOP_INTERVAL_SECS,
    MARKET_COOLDOWN_SECS,
    MAX_CANDIDATES,
    MAX_DEPLOY_FRACTION,
    MAX_ENTRY_PRICE,
    MAX_OPEN_POSITIONS,
    PORTFOLIO_WALLET,
)
from gamma import fetch_markets, fetch_news
from positions import fetch_held_positions
from storage import load_seen_markets, log_cycle_jsonl, save_seen_markets
from telegram import send_telegram

logger = logging.getLogger(__name__)


def run_cycle() -> None:
    cycle_start_ts = time.time()
    cycle_iso      = datetime.now(timezone.utc).isoformat()
    logger.info("═" * 60)
    logger.info(f"── Cycle start  {cycle_iso} ──")

    # 0. Claim any resolved positions on-chain so they drop off held-set
    try:
        redemptions.redeem_resolved_positions()
    except Exception as e:
        logger.error(f"  redemption step failed: {e}", exc_info=True)

    # 1. Balance + live positions
    balance   = fetch_usdc_balance()
    positions = fetch_held_positions()
    held_ids  = {p.condition_id for p in positions}

    redeemable_count = sum(1 for p in positions if p.redeemable)
    live_count       = len(positions) - redeemable_count
    logger.info(
        f"  Balance=${balance:.2f}  positions={len(positions)}/{MAX_OPEN_POSITIONS}  "
        f"(live={live_count}  redeemable={redeemable_count}, not sent to Claude)"
    )
    for p in positions:
        logger.info(
            f"    HOLD {p.condition_id[:10]}…  {p.outcome:<4}  "
            f"entry={p.avg_price:.3f}  now={p.current_price:.3f}  "
            f"size={p.size_shares:7.1f}  pnl={p.cash_pnl:+7.2f} ({p.percent_pnl:+6.1f}%)  "
            f"{'REDEEMABLE  ' if p.redeemable else ''}'{p.question[:50]}'"
        )

    # 2. Candidate list — pagination, skip held + recently-checked (cooldown).
    seen_markets = load_seen_markets()
    now_epoch    = time.time()
    seen_markets = {k: v for k, v in seen_markets.items() if now_epoch - v < 7 * 86400}

    candidates: list = []
    offset = 0
    fetched_total  = 0
    skipped_held   = 0
    skipped_recent = 0
    while len(candidates) < MAX_CANDIDATES:
        markets, raw_count = fetch_markets(offset=offset, limit=100)
        fetched_total += len(markets)
        if not markets and raw_count == 0:
            break
        for m in markets:
            if m.condition_id in held_ids:
                skipped_held += 1
                continue
            last_seen = seen_markets.get(m.condition_id, 0)
            if now_epoch - last_seen < MARKET_COOLDOWN_SECS:
                skipped_recent += 1
                continue
            candidates.append((m, fetch_news(m.question)))
            if len(candidates) >= MAX_CANDIDATES:
                break
        if raw_count < 100:
            break
        offset += 100

    logger.info(
        f"  Candidates: fetched={fetched_total}  "
        f"skipped_held={skipped_held}  skipped_cooldown={skipped_recent}  "
        f"selected={len(candidates)}  target={MAX_CANDIDATES}  cooldown={MARKET_COOLDOWN_SECS//3600}h"
    )
    for idx, (m, _news) in enumerate(candidates):
        price_summary = " ".join(f"{o.label}={o.price:.2f}" for o in m.outcomes[:4])
        logger.info(
            f"    CAND [{idx:02d}] {m.condition_id[:10]}…  "
            f"{m.days_to_close:4.0f}d  vol=${m.volume_24h:>10,.0f}  "
            f"[{price_summary}]  '{m.question[:55]}'"
        )

    for m, _news in candidates:
        seen_markets[m.condition_id] = now_epoch
    save_seen_markets(seen_markets)

    max_deploy = balance * MAX_DEPLOY_FRACTION
    logger.info(f"  Cycle budget: ${max_deploy:.2f}  (={MAX_DEPLOY_FRACTION:.0%} of ${balance:.2f})")

    if not CLAUDE_ENABLED:
        logger.info("  CLAUDE_ENABLED=false — skipping Claude call")
        return

    if balance < BET_SIZE_MIN and not positions:
        logger.warning(f"  Balance ${balance:.2f} < floor and no positions — skipping Claude")
        log_cycle_jsonl({
            "ts": cycle_iso, "skipped": "insufficient_balance",
            "balance": balance, "positions": 0, "candidates": len(candidates),
        })
        return

    # 3. Ask Claude
    claude_start = time.time()
    actions      = ask_claude(positions, candidates, balance)
    claude_secs  = time.time() - claude_start
    logger.info(f"  Claude call took {claude_secs:.1f}s, returned {len(actions)} action(s)")

    if not actions:
        log_cycle_jsonl({
            "ts": cycle_iso, "balance": balance,
            "positions": len(positions), "candidates": len(candidates),
            "actions": [], "note": "empty_response",
        })
        return

    by_cid        = {p.condition_id: p for p in positions}
    deployed      = 0.0
    opened_count  = 0
    cycle_actions: list = []

    kind_counts = {"OPEN": 0, "ADD": 0, "EXIT": 0, "HOLD": 0, "UNKNOWN": 0}
    for a in actions:
        kind_counts[str(a.get("action", "")).upper() if str(a.get("action", "")).upper() in kind_counts else "UNKNOWN"] += 1
    logger.info(
        f"  Action breakdown: OPEN={kind_counts['OPEN']}  ADD={kind_counts['ADD']}  "
        f"EXIT={kind_counts['EXIT']}  HOLD={kind_counts['HOLD']}  UNK={kind_counts['UNKNOWN']}"
    )

    for a in actions:
        try:
            kind = str(a.get("action", "")).upper()
            why  = (a.get("why") or "")[:200]

            if kind == "HOLD":
                cid = a.get("cid", "")
                p   = by_cid.get(cid)
                logger.info(f"  HOLD  {cid[:10]}…  '{(p.question if p else '')[:60]}'  — {why}")
                cycle_actions.append({"kind": "HOLD", "cid": cid, "why": why, "executed": True})
                continue

            if kind == "EXIT":
                cid = a.get("cid", "")
                p   = by_cid.get(cid)
                if not p:
                    logger.warning(f"  EXIT ignored — unknown cid {cid[:10]}…")
                    cycle_actions.append({"kind": "EXIT", "cid": cid, "why": why, "executed": False, "error": "unknown_cid"})
                    continue
                if p.redeemable:
                    logger.info(f"  EXIT skipped — redeemable, claim on-chain: {cid[:10]}…")
                    cycle_actions.append({"kind": "EXIT", "cid": cid, "why": why, "executed": False, "error": "redeemable"})
                    continue
                logger.info(
                    f"  EXIT  '{p.outcome}' in '{p.question[:60]}'  "
                    f"size={p.size_shares:.1f}  now={p.current_price:.3f}  pnl={p.cash_pnl:+.2f} ({p.percent_pnl:+.1f}%) — {why}"
                )
                order_id = place_sell(p.token_id, p.size_shares, p.neg_risk, label=p.outcome)
                cycle_actions.append({
                    "kind": "EXIT", "cid": cid, "question": p.question, "outcome": p.outcome,
                    "size_shares": p.size_shares, "price": p.current_price,
                    "pnl": p.cash_pnl, "percent_pnl": p.percent_pnl,
                    "why": why, "order_id": order_id, "executed": order_id is not None,
                })
                if order_id:
                    send_telegram(
                        f"🏁 <b>EXIT{' [DRY]' if DRY_RUN else ''}</b>\n"
                        f"<b>Market:</b> {p.question}\n"
                        f"<b>Side:</b> {p.outcome}  size={p.size_shares:.1f}\n"
                        f"<b>PnL:</b> {p.cash_pnl:+.2f} ({p.percent_pnl:+.1f}%)\n"
                        f"<b>Why:</b> {why}"
                    )
                continue

            if kind == "ADD":
                cid   = a.get("cid", "")
                size  = float(a.get("size") or 0)
                p     = by_cid.get(cid)
                if not p:
                    logger.warning(f"  ADD ignored — unknown cid {cid[:10]}…")
                    cycle_actions.append({"kind": "ADD", "cid": cid, "why": why, "executed": False, "error": "unknown_cid"})
                    continue
                if size < BET_SIZE_MIN:
                    logger.info(f"  ADD skipped — Claude size ${size:.2f} below floor ${BET_SIZE_MIN:.2f}")
                    cycle_actions.append({"kind": "ADD", "cid": cid, "size": size, "why": why, "executed": False, "error": "below_floor"})
                    continue
                if deployed + size > max_deploy:
                    logger.info(f"  ADD throttled — ${size:.2f} would exceed ${max_deploy:.2f} cycle budget")
                    cycle_actions.append({"kind": "ADD", "cid": cid, "size": size, "why": why, "executed": False, "error": "budget_exceeded"})
                    continue
                if p.current_price > MAX_ENTRY_PRICE:
                    logger.info(f"  ADD skipped — price {p.current_price:.1%} > ceiling {MAX_ENTRY_PRICE:.0%}")
                    cycle_actions.append({"kind": "ADD", "cid": cid, "size": size, "why": why, "executed": False, "error": "price_over_ceiling"})
                    continue
                limit = p.current_price + 0.01
                logger.info(f"  ADD   '{p.outcome}' in '{p.question[:60]}'  ${size:.2f} @ {limit:.3f} — {why}")
                order_id = place_buy(p.token_id, limit, size, p.neg_risk, label=p.outcome)
                cycle_actions.append({
                    "kind": "ADD", "cid": cid, "question": p.question, "outcome": p.outcome,
                    "size": size, "price": p.current_price, "limit": limit,
                    "why": why, "order_id": order_id, "executed": order_id is not None,
                })
                if order_id:
                    deployed += size
                    send_telegram(
                        f"➕ <b>ADD{' [DRY]' if DRY_RUN else ''}</b>\n"
                        f"<b>Market:</b> {p.question}\n"
                        f"<b>Side:</b> {p.outcome} @ {p.current_price:.0%}\n"
                        f"<b>Size:</b> ${size:.2f}\n"
                        f"<b>Why:</b> {why}"
                    )
                continue

            if kind == "OPEN":
                i    = int(a.get("i", -1))
                o    = int(a.get("o", -1))
                size = float(a.get("size") or 0)
                if i < 0 or i >= len(candidates):
                    logger.warning(f"  OPEN invalid market index {i}")
                    cycle_actions.append({"kind": "OPEN", "i": i, "o": o, "size": size, "why": why, "executed": False, "error": "invalid_i"})
                    continue
                market = candidates[i][0]
                if o < 0 or o >= len(market.outcomes):
                    logger.warning(f"  OPEN invalid outcome index {o}")
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "i": i, "o": o, "size": size, "why": why, "executed": False, "error": "invalid_o"})
                    continue
                outcome = market.outcomes[o]
                if outcome.price > MAX_ENTRY_PRICE:
                    logger.info(f"  OPEN skipped — price {outcome.price:.1%} > ceiling {MAX_ENTRY_PRICE:.0%}  '{market.question[:55]}'")
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "outcome": outcome.label, "price": outcome.price, "size": size, "why": why, "executed": False, "error": "price_over_ceiling"})
                    continue
                if live_count + opened_count >= MAX_OPEN_POSITIONS:
                    logger.info(
                        f"  OPEN skipped — live portfolio cap {MAX_OPEN_POSITIONS} reached "
                        f"(live={live_count} redeemable={redeemable_count})"
                    )
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "outcome": outcome.label, "size": size, "why": why, "executed": False, "error": "portfolio_cap"})
                    continue
                if size < BET_SIZE_MIN:
                    logger.info(f"  OPEN skipped — Claude size ${size:.2f} below floor ${BET_SIZE_MIN:.2f}")
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "outcome": outcome.label, "size": size, "why": why, "executed": False, "error": "below_floor"})
                    continue
                if deployed + size > max_deploy:
                    logger.info(f"  OPEN throttled — ${size:.2f} would exceed ${max_deploy:.2f} cycle budget")
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "outcome": outcome.label, "size": size, "why": why, "executed": False, "error": "budget_exceeded"})
                    continue
                if size < market.min_size:
                    logger.info(f"  OPEN skipped — size ${size:.2f} below market min ${market.min_size:.2f}")
                    cycle_actions.append({"kind": "OPEN", "cid": market.condition_id, "outcome": outcome.label, "size": size, "why": why, "executed": False, "error": "below_market_min"})
                    continue
                limit = outcome.price + 0.01
                logger.info(
                    f"  OPEN  '{outcome.label}' @ {outcome.price:.1%} in '{market.question[:55]}'  "
                    f"${size:.2f} @ {limit:.3f}  ({market.days_to_close:.0f}d) — {why}"
                )
                order_id = place_buy(outcome.token_id, limit, size, market.neg_risk, label=outcome.label)
                cycle_actions.append({
                    "kind": "OPEN", "cid": market.condition_id, "question": market.question,
                    "outcome": outcome.label, "price": outcome.price, "size": size, "limit": limit,
                    "days_to_close": market.days_to_close, "why": why,
                    "order_id": order_id, "executed": order_id is not None,
                })
                if order_id:
                    opened_count += 1
                    deployed     += size
                    send_telegram(
                        f"🎯 <b>OPEN{' [DRY]' if DRY_RUN else ''}</b>\n"
                        f"<b>Market:</b> {market.question}\n"
                        f"<b>Side:</b> {outcome.label} @ {outcome.price:.0%}\n"
                        f"<b>Size:</b> ${size:.2f}\n"
                        f"<b>Why:</b> {why}"
                    )
                continue

            logger.warning(f"  Unknown action kind: {kind}  raw={a}")
            cycle_actions.append({"kind": "UNKNOWN", "raw": a, "executed": False})
        except Exception as e:
            logger.warning(f"  Action processing failed for {a}: {e}")
            cycle_actions.append({"kind": "ERROR", "raw": a, "error": str(e), "executed": False})

    cycle_secs = time.time() - cycle_start_ts
    logger.info(
        f"  Cycle done in {cycle_secs:.1f}s  "
        f"deployed=${deployed:.2f}/${max_deploy:.2f}  "
        f"opened={opened_count}  actions={len(cycle_actions)}"
    )

    log_cycle_jsonl({
        "ts":         cycle_iso,
        "duration_s": round(cycle_secs, 1),
        "balance":    balance,
        "max_deploy": max_deploy,
        "deployed":   round(deployed, 2),
        "opened":     opened_count,
        "positions": [{
            "cid": p.condition_id, "outcome": p.outcome, "question": p.question,
            "size": p.size_shares, "avg": p.avg_price, "cur": p.current_price,
            "pnl": p.cash_pnl, "pct": p.percent_pnl, "redeemable": p.redeemable,
        } for p in positions],
        "candidates_sent":    len(candidates),
        "candidates_fetched": fetched_total,
        "skipped_held":       skipped_held,
        "skipped_cooldown":   skipped_recent,
        "action_counts":      kind_counts,
        "actions":            cycle_actions,
    })


def main() -> None:
    logger.info("═" * 60)
    logger.info("Polymarket Portfolio Bot — startup")
    logger.info("═" * 60)

    if not check_anthropic_connection():
        send_telegram("🚨 Portfolio bot: Anthropic API check failed")
        sys.exit(1)

    ensure_allowances()

    balance = fetch_usdc_balance()
    if balance <= 0 and not DRY_RUN:
        logger.warning(f"  Balance is ${balance:.2f} — will only manage existing positions")

    logger.info(
        f"Ready  dry_run={DRY_RUN}  wallet={PORTFOLIO_WALLET}  "
        f"balance=${balance:.2f}  interval={LOOP_INTERVAL_SECS}s  "
        f"max_deploy={MAX_DEPLOY_FRACTION:.0%}  model={CLAUDE_MODEL}"
    )
    send_telegram(
        f"🤖 <b>Portfolio Bot started</b>\n"
        f"dry_run={DRY_RUN}  balance=${balance:.2f}\n"
        f"interval={LOOP_INTERVAL_SECS}s  max_deploy={MAX_DEPLOY_FRACTION:.0%}"
    )

    while True:
        try:
            run_cycle()
        except Exception as e:
            logger.error(f"Cycle failed: {e}", exc_info=True)
            send_telegram(f"⚠️ Portfolio bot error: {e}")
        logger.info(f"Sleeping {LOOP_INTERVAL_SECS}s …\n")
        time.sleep(LOOP_INTERVAL_SECS)


if __name__ == "__main__":
    main()
