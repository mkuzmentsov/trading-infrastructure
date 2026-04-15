"""Claude portfolio-manager prompt + response parsing."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    BET_SIZE_MIN,
    CLAUDE_MODEL,
    MAX_DEPLOY_FRACTION,
    MAX_ENTRY_PRICE,
    MAX_OPEN_POSITIONS,
    MIN_DAYS_TO_CLOSE,
)

logger = logging.getLogger(__name__)

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def check_anthropic_connection() -> bool:
    logger.info("Checking Anthropic API connection …")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        logger.info(f"  Anthropic OK — model={resp.model}  stop={resp.stop_reason}")
        return True
    except anthropic.AuthenticationError:
        logger.error("  Anthropic FAILED — invalid API key")
        return False
    except Exception as e:
        logger.error(f"  Anthropic FAILED — {e}")
        return False


def ask_claude(positions: list, candidates: list, balance_usdc: float) -> list:
    """
    Send portfolio + candidates to Claude. Claude returns a list of action dicts:
      [
        {"action": "OPEN",  "i": 3, "o": 1, "size": 5.0, "why": "..."},
        {"action": "ADD",   "cid": "0x..", "size": 3.0, "why": "..."},
        {"action": "EXIT",  "cid": "0x..",               "why": "..."},
        {"action": "HOLD",  "cid": "0x..",               "why": "..."}
      ]
    """
    if _claude is None:
        logger.error("  Anthropic client uninitialized (no API key)")
        return []

    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    max_deploy = round(balance_usdc * MAX_DEPLOY_FRACTION, 2)

    # Redeemable positions are on-chain claims, not trading decisions — strip them
    # so Claude doesn't waste tokens EXIT-ing capital that's already been settled.
    positions = [p for p in positions if not p.redeemable]

    if positions:
        pos_lines = []
        for p in positions:
            days_left = ""
            if p.end_date:
                try:
                    end = datetime.fromisoformat(p.end_date.replace("Z", "+00:00"))
                    days_left = f"{(end - datetime.now(timezone.utc)).days}d left"
                except Exception:
                    pass
            pos_lines.append(
                f"  cid={p.condition_id} '{p.outcome}' in '{p.question[:70]}'\n"
                f"     entry={p.avg_price:.3f}  now={p.current_price:.3f}  "
                f"size={p.size_shares:.1f}  pnl={p.cash_pnl:+.2f} ({p.percent_pnl:+.1f}%)  "
                f"{days_left}{'  REDEEMABLE' if p.redeemable else ''}"
            )
        positions_block = "EXISTING POSITIONS:\n" + "\n".join(pos_lines)
    else:
        positions_block = "EXISTING POSITIONS: none"

    open_slots = max(0, MAX_OPEN_POSITIONS - len(positions))

    cand_sections = []
    for idx, (market, news) in enumerate(candidates):
        outcome_lines = "  ".join(
            f"[{i}] {o.label} {o.price:.1%}"
            for i, o in enumerate(market.outcomes)
        )
        cand_sections.append(
            f"[{idx}] cid={market.condition_id} {market.question}\n"
            f"    Resolves: {market.end_date} ({market.days_to_close:.0f}d)"
            f" | Vol24h: ${market.volume_24h:,.0f} | MinOrder: ${market.min_size:.2f}\n"
            f"    Outcomes: {outcome_lines}\n"
            f"    {market.description[:200] if market.description else ''}"
            + (f"\n    News: {news[:300]}" if news else "")
        )
    candidates_block = "NEW CANDIDATE MARKETS:\n" + ("\n".join(cand_sections) if cand_sections else "  (none)")

    prompt = f"""Today is {today}. You are a prediction-market portfolio manager.

Free USDC balance: ${balance_usdc:.2f}
New-position budget this cycle: ${max_deploy:.2f}
Open positions: {len(positions)} / {MAX_OPEN_POSITIONS} (may OPEN up to {open_slots} more)
Per-bet floor: ${BET_SIZE_MIN:.2f} (dust). Entry price ceiling: {MAX_ENTRY_PRICE:.0%}.
Only candidate markets resolving ≥ {MIN_DAYS_TO_CLOSE} days out are listed.

YOU decide every bet size. Size should reflect:
 - your conviction (stronger edge → larger size)
 - the balance (don't over-concentrate; the ${max_deploy:.2f} cycle cap is a hard ceiling)
 - the outcome's price (cheaper tails can take smaller absolute sizes)

{positions_block}

{candidates_block}

Your job: decide what to do, holistically.
- For EVERY existing position, pick exactly one of EXIT, HOLD, or ADD.
- For NEW candidates you may pick OPEN on specific outcomes. Only when conviction is real.

Critical rules:
- If the outcome's price is NOT REALISTICALLY GOING TO MOVE IN OUR FAVOR before resolution,
  DO NOT bet on it. Skip it entirely. No size can compensate for a losing thesis.
- EXIT when thesis broke, news turned, or profit is material and decay/time risk is rising.
  Also EXIT positions flagged REDEEMABLE (market resolved our way — claim & free capital).
- ADD when conviction grew or price dropped without new bad news.
- OPEN on outcomes priced below {MAX_ENTRY_PRICE:.0%} with genuine mispricing vs your true prob.
- Total OPEN + ADD sizes must not exceed ${max_deploy:.2f}.
- OPEN count must not exceed {open_slots} (portfolio cap {MAX_OPEN_POSITIONS}).

Respond with ONLY a JSON array. Each element is one action:
[
  {{"action":"EXIT","cid":"0xabc...","why":"news turned, thesis broken"}},
  {{"action":"HOLD","cid":"0xdef...","why":"on track, let it ride"}},
  {{"action":"ADD","cid":"0xghi...","size":3.0,"why":"price dipped, conviction up"}},
  {{"action":"OPEN","i":4,"o":1,"size":5.0,"why":"15% priced, fair ~35%"}}
]

- Include an action for EVERY existing position.
- "i" = candidate index, "o" = outcome index within that candidate.
- "cid" = full conditionId starting with 0x (copy from the line above).
- Output valid JSON only, no prose, no markdown."""

    try:
        resp = _claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system="You are a quantitative prediction-market portfolio manager. Output ONLY valid JSON arrays.",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error(f"  Claude API error: {e}")
        return []

    text = resp.content[0].text.strip() if resp.content else ""
    logger.info(f"  Claude raw response: {text[:600]}")

    try:
        start = text.index('[')
        actions, _ = json.JSONDecoder().raw_decode(text, start)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"  Failed to parse Claude JSON: {e}\nRaw: {text[:400]}")
        return []

    logger.info(f"  Claude returned {len(actions)} action(s)")
    return actions
