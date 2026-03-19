#!/usr/bin/env python3
"""
Polymarket Claude Bot
=====================
Scans active Polymarket prediction markets, fetches recent news via DuckDuckGo,
then passes ALL candidate markets to Claude in a single batch call. Claude acts
as a portfolio manager — it sees the full list, the current USDC balance, and
decides which markets to bet on and exactly how much to allocate to each.

Startup checks (bot exits on failure):
  1. Anthropic API connectivity — verifies the API key works before doing anything
  2. USDC balance — fetches on-chain balance from Polygon and aborts if zero

Environment variables (set via Kubernetes Secret):
  ANTHROPIC_API_KEY         Claude API key (required)
  POLYMARKET_PK             Polygon wallet private key, hex 0x... (required to sign orders)
  POLYMARKET_ADDRESS        Polygon wallet address 0x... (required)
  POLYMARKET_API_KEY        Polymarket CLOB API key (optional — auto-generated if absent)
  POLYMARKET_API_SECRET     Polymarket CLOB API secret (optional)
  POLYMARKET_API_PASSPHRASE Polymarket CLOB API passphrase (optional)
  DRY_RUN                   "true" to simulate without placing orders (default: true)
  MIN_MARKET_VOLUME         Min 24h volume USD to consider a market (default: 50000)
  MIN_EDGE                  Min probability edge to include a market as candidate (default: 0.08)
  MAX_DEPLOY_FRACTION       Max fraction of balance Claude may allocate per loop (default: 0.30)
  MAX_MARKETS_PER_LOOP      Max candidate markets to send to Claude per cycle (default: 15)
  LOOP_INTERVAL_SECS        Seconds between scan cycles (default: 600)
  TELEGRAM_TOKEN            Telegram bot token for notifications (optional)
  TELEGRAM_CHAT_ID          Telegram chat ID (optional)
  DATA_DIR                  Directory for persistent state (default: /app/data)
"""

import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY         = os.environ["ANTHROPIC_API_KEY"]
POLYMARKET_PK             = os.environ.get("POLYMARKET_PK", "")
POLYMARKET_ADDRESS        = os.environ.get("POLYMARKET_ADDRESS", "")
POLYMARKET_API_KEY        = os.environ.get("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET     = os.environ.get("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE  = os.environ.get("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_SIGNATURE_TYPE  = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0"))  # 0=EOA, 2=Gnosis Safe
POLYMARKET_FUNDER          = os.environ.get("POLYMARKET_FUNDER", "")  # for Gnosis Safe: the Safe address; leave empty for EOA
DRY_RUN                   = os.environ.get("DRY_RUN", "true").lower() == "true"
MIN_MARKET_VOLUME         = float(os.environ.get("MIN_MARKET_VOLUME", "50000"))
MIN_EDGE                  = float(os.environ.get("MIN_EDGE", "0.05"))
MAX_DEPLOY_FRACTION       = float(os.environ.get("MAX_DEPLOY_FRACTION", "0.20"))
MAX_MARKETS_PER_LOOP      = int(os.environ.get("MAX_MARKETS_PER_LOOP", "40"))
BET_SIZE_MIN              = float(os.environ.get("BET_SIZE_MIN", "1.0"))
BET_SIZE_MAX              = float(os.environ.get("BET_SIZE_MAX", "25"))
LOOP_INTERVAL_SECS        = int(os.environ.get("LOOP_INTERVAL_SECS", "600"))
CLAUDE_ENABLED            = os.environ.get("CLAUDE_ENABLED", "true").lower() == "true"
TELEGRAM_TOKEN            = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID          = os.environ.get("TELEGRAM_CHAT_ID", "")
DATA_DIR                  = Path(os.environ.get("DATA_DIR", "/app/data"))

GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
CHAIN_ID   = 137   # Polygon mainnet

# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    label:    str
    price:    float   # 0–1 implied probability
    token_id: str


@dataclass
class Market:
    condition_id: str
    question:     str
    description:  str
    volume_24h:   float
    volume_total: float
    end_date:     str
    neg_risk:     bool
    min_size:     float  # minimum order size in USDC (from orderMinSize)
    outcomes:     list  # list of Outcome


@dataclass
class Assessment:
    outcome_idx:   int    # index into market.outcomes
    outcome_label: str
    price:         float  # price of selected outcome
    probability:   float  # Claude's estimate
    edge:          float
    bet_usdc:      float
    reasoning:     str


@dataclass
class Position:
    condition_id: str
    question:     str
    outcome:      str
    token_id:     str
    entry_price:  float
    size_usdc:    float
    order_id:     str
    timestamp:    str


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(msg: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


# ── Position persistence ───────────────────────────────────────────────────────

def _positions_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "positions.json"


def load_positions() -> dict[str, Position]:
    """
    Load existing positions from Polymarket API (open orders + filled trades).
    Falls back to local filesystem cache if API is unavailable.
    """
    try:
        clob     = _get_clob_client()
        positions: dict[str, Position] = {}

        # 1. Open / pending orders
        orders = clob.get_orders() or []
        logger.info(f"  get_orders: {len(orders)} open order(s)")
        for o in orders:
            cid = o.get("market") or o.get("conditionId", "")
            if not cid or cid in positions:
                continue
            positions[cid] = Position(
                condition_id = cid,
                question     = cid,
                outcome      = o.get("side", ""),
                token_id     = o.get("asset_id", ""),
                entry_price  = float(o.get("price") or 0),
                size_usdc    = float(o.get("original_size") or o.get("size_matched") or 0),
                order_id     = o.get("id", ""),
                timestamp    = str(o.get("created_at", "")),
            )

        # 2. Filled trades (BUY side = positions we hold)
        trades = clob.get_trades() or []
        logger.info(f"  get_trades: {len(trades)} trade(s)")
        for t in trades:
            if t.get("side", "").upper() not in ("BUY", "MAKER"):
                continue
            cid = t.get("market", "") or t.get("conditionId", "") or t.get("condition_id", "")
            if not cid or cid in positions:
                continue
            positions[cid] = Position(
                condition_id = cid,
                question     = cid,
                outcome      = t.get("outcome", ""),
                token_id     = t.get("asset_id", ""),
                entry_price  = float(t.get("price") or 0),
                size_usdc    = float(t.get("size") or 0),
                order_id     = t.get("id", ""),
                timestamp    = str(t.get("created_at", "")),
            )

        logger.info(f"  Loaded {len(positions)} position(s) from API")
        return positions

    except Exception as e:
        logger.warning(f"  API position load failed: {e} — falling back to local cache")
        p = _positions_path()
        if not p.exists():
            return {}
        try:
            raw = json.loads(p.read_text())
            return {k: Position(**v) for k, v in raw.items()}
        except Exception:
            return {}


def save_positions(positions: dict[str, Position]) -> None:
    """Save positions to local cache (used as fallback if API is unavailable)."""
    try:
        _positions_path().write_text(
            json.dumps({k: asdict(v) for k, v in positions.items()}, indent=2)
        )
    except Exception:
        pass


# ── Startup checks ─────────────────────────────────────────────────────────────

def check_anthropic_connection() -> bool:
    """
    Verify the Anthropic API key is valid and the service is reachable.
    Uses a minimal claude-haiku call to minimise cost and latency.
    Returns True on success, False on any error.
    """
    logger.info("Checking Anthropic API connection …")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        # Any response (even a short one) confirms the key and endpoint work
        logger.info(f"  Anthropic OK — model={resp.model}  stop={resp.stop_reason}")
        return True
    except anthropic.AuthenticationError:
        logger.error("  Anthropic FAILED — invalid API key")
        return False
    except Exception as e:
        logger.error(f"  Anthropic FAILED — {e}")
        return False


_cached_clob_client = None

def _get_clob_client():
    """Return an initialised ClobClient, creating or deriving API credentials automatically."""
    global _cached_clob_client
    if _cached_clob_client is not None:
        return _cached_clob_client

    from py_clob_client.client import ClobClient

    client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=POLYMARKET_PK,
        signature_type=POLYMARKET_SIGNATURE_TYPE,
        funder=POLYMARKET_FUNDER if POLYMARKET_FUNDER else None,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    logger.info(f"  CLOB client ready  address={client.get_address()}  sig_type={POLYMARKET_SIGNATURE_TYPE}")

    _cached_clob_client = client
    return client


def ensure_allowances() -> None:
    """Approve Polymarket exchange contracts to spend USDC (one-time setup)."""
    if DRY_RUN:
        return
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = _get_clob_client()
        result = clob.update_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        logger.info(f"  update_balance_allowance response: {result}")
    except Exception as e:
        logger.warning(f"  Allowance update failed: {e}")


def fetch_usdc_balance() -> float:
    """Fetch available USDC balance from Polymarket via py-clob-client."""
    if DRY_RUN:
        simulated = 500.0
        logger.info(f"  Balance: DRY RUN — simulated ${simulated:.2f}")
        return simulated
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = _get_clob_client()
        data = clob.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        logger.info(f"  get_balance_allowance response: {data}")
        bal  = float(data.get("balance", 0)) / 1_000_000  # USDC has 6 decimals
        logger.info(f"  Balance: ${bal:.2f} USDC")
        return bal
    except Exception as e:
        logger.warning(f"  Balance check failed: {e}")
        return 0.0


# ── Market data ────────────────────────────────────────────────────────────────

def fetch_markets(offset: int = 0, limit: int = 100) -> tuple:
    """Fetch active markets from Polymarket Gamma API, sorted by 24h volume."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "closed": "false", "limit": limit, "offset": offset,
                    "order": "volume24hr", "ascending": "false"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch markets: {e}")
        return [], 0

    now = datetime.now(timezone.utc)
    markets: list[Market] = []
    raw = resp.json()
    logger.info(f"  fetch_markets response: {resp.status_code}  total_rows={len(raw)}")
    skipped_tokens = skipped_vol = skipped_expiry = 0

    for m in raw:
        try:
            token_ids = m.get("clobTokenIds") or []
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if len(token_ids) < 2:
                skipped_tokens += 1
                continue

            labels_raw = m.get("outcomes") or []
            if isinstance(labels_raw, str):
                labels_raw = json.loads(labels_raw)

            prices_raw = m.get("outcomePrices") or []
            if isinstance(prices_raw, str):
                prices_raw = json.loads(prices_raw)

            # Pad labels/prices to match token count
            while len(labels_raw) < len(token_ids):
                labels_raw.append(f"Outcome {len(labels_raw)}")
            while len(prices_raw) < len(token_ids):
                prices_raw.append("0.5")

            outcomes = [
                Outcome(
                    label    = str(labels_raw[i]),
                    price    = float(prices_raw[i]),
                    token_id = str(token_ids[i]),
                )
                for i in range(len(token_ids))
            ]

            # Skip markets where all outcomes are near-resolved (>99% or <1%)
            if all(o.price < 0.01 or o.price > 0.99 for o in outcomes):
                skipped_tokens += 1
                continue

            vol_24h = float(m.get("volume24hr") or m.get("volume24Hr") or m.get("volumeNum") or 0)
            if vol_24h < MIN_MARKET_VOLUME:
                skipped_vol += 1
                continue

            end_date_str = m.get("endDate", "")
            if end_date_str:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if (end_dt - now).total_seconds() < 86400:
                    skipped_expiry += 1
                    continue

            markets.append(Market(
                condition_id = m.get("conditionId") or m.get("id", ""),
                question     = m.get("question", ""),
                description  = (m.get("description") or "")[:500],
                volume_24h   = vol_24h,
                volume_total = float(m.get("volume") or 0),
                end_date     = end_date_str,
                neg_risk     = bool(m.get("negRisk") or m.get("neg_risk") or False),
                min_size     = float(m.get("orderMinSize") or m.get("minOrderSize") or 1.0),
                outcomes     = outcomes,
            ))
        except Exception as e:
            logger.warning(f"Skipping market (parse error): {e}")

    logger.info(
        f"  Fetched {len(raw)} markets — kept {len(markets)} "
        f"(skipped: no_tokens={skipped_tokens} vol={skipped_vol} expiry={skipped_expiry})"
    )
    return markets, len(raw)  # (filtered markets, raw API count for pagination)


# ── News search ────────────────────────────────────────────────────────────────

def fetch_news(query: str, max_results: int = 5) -> str:
    """Search DuckDuckGo for recent news. Returns a short formatted string."""
    try:
        from duckduckgo_search import DDGS
        results = DDGS().news(query, max_results=max_results)
        if not results:
            return "No recent news found."
        lines = []
        for r in results:
            date  = r.get("date", "?")
            title = r.get("title", "")
            body  = (r.get("body") or "")[:200]
            lines.append(f"[{date}] {title} — {body}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"News fetch failed ('{query[:50]}'): {e}")
        return "News search unavailable."


# ── Claude batch portfolio assessment ─────────────────────────────────────────

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def assess_markets_batch(
    candidates: list,   # list[Market] or list[tuple[Market, str]]
    balance_usdc: float,
    held_count: int,
) -> list[tuple[int, Assessment]]:
    """
    Send all candidate markets to Claude. Claude responds with a plain JSON array
    of positions — no tool schema, no array that can be left empty.
    Returns list of (market_index, Assessment) pairs.
    """
    if not candidates:
        return []

    max_deploy = round(balance_usdc * MAX_DEPLOY_FRACTION, 2)
    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    market_sections = []
    for idx, item in enumerate(candidates):
        market = item[0] if isinstance(item, tuple) else item
        news   = item[1] if isinstance(item, tuple) else ""
        outcome_lines = "  ".join(
            f"[{i}] {o.label} {o.price:.1%} ({round(1/o.price,1) if o.price > 0 else '?'}x)"
            for i, o in enumerate(market.outcomes)
        )
        section = (
            f"[{idx}] {market.question}\n"
            f"    Resolves: {market.end_date} | Vol: ${market.volume_24h:,.0f} | Min order: ${market.min_size:.2f}\n"
            f"    Outcomes: {outcome_lines}\n"
            f"    {market.description[:200] if market.description else ''}"
            + (f"\n    News: {news[:300]}" if news else "")
        )
        market_sections.append(section)

    prompt = f"""Today is {today}. You are a prediction market analyst.

Analyze the {len(candidates)} markets below and output trading signals.
Budget: ${max_deploy:.2f} USDC total. Each position: ${BET_SIZE_MIN:.2f}–${BET_SIZE_MAX:.2f} USDC (min $1.00).

Strategy: SPECULATIVE — focus exclusively on LOW-PROBABILITY outcomes (priced under 25%).
A 2% outcome pays 50x. A 5% outcome pays 20x. These are the only bets worth making.
NEVER bet on an outcome priced above 25% — the return is too low to justify the risk.
Target 10–20 positions per cycle across different markets and topics.

Rules:
- Only pick outcomes priced UNDER 25% (the lower the price, the higher the payout)
- Bet when your estimated true probability is meaningfully higher than the market price
- Skip any outcome above 25% — even if it seems likely, the profit potential is too small
- Scale size: ${BET_SIZE_MAX:.2f} = strong edge on a very underpriced outcome, $1 = speculative long-shot
- IMPORTANT: each market shows "Min order: $X" — your size must be ≥ that minimum or skip the market

MARKETS:
{chr(10).join(market_sections)}

Respond with ONLY a JSON array, no other text. Example format:
[
  {{"i": 3, "o": 1, "prob": 0.45, "size": 5.0, "why": "reason"}},
  {{"i": 7, "o": 0, "prob": 0.15, "size": 1.0, "why": "reason"}}
]
"i" = market index, "o" = outcome index within that market, "prob" = your probability for that outcome.
If nothing has edge, respond with: []"""

    try:
        resp = _claude.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=(
                "You are a quantitative prediction market analyst. "
                "Output ONLY valid JSON arrays as instructed. No commentary, no markdown."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return []

    text = resp.content[0].text.strip() if resp.content else ""
    logger.info(f"  Claude raw response: {text[:500]}")

    try:
        start = text.index('[')
        raw_bets, _ = json.JSONDecoder().raw_decode(text, start)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse Claude JSON: {e}\nRaw: {text[:300]}")
        return []

    logger.info(f"  Claude returned {len(raw_bets)} position(s)")

    results: list[tuple[int, Assessment]] = []
    total_allocated = 0.0

    for bet in raw_bets:
        try:
            idx           = int(bet["i"])
            outcome_idx   = int(bet["o"])
            prob          = float(bet["prob"])
            size          = float(bet["size"])
            reasoning     = bet.get("why", "")
        except (KeyError, ValueError) as e:
            logger.warning(f"  Skipping malformed bet {bet}: {e}")
            continue

        if idx < 0 or idx >= len(candidates):
            logger.warning(f"  Invalid market index {idx} — skip")
            continue

        market = candidates[idx][0] if isinstance(candidates[idx], tuple) else candidates[idx]

        if outcome_idx < 0 or outcome_idx >= len(market.outcomes):
            logger.warning(f"  Invalid outcome index {outcome_idx} for market {idx} — skip")
            continue

        outcome  = market.outcomes[outcome_idx]

        # Hard filter: skip near-certain outcomes — return is too low
        if outcome.price > 0.30:
            logger.info(f"  Skipping [{idx}:{outcome_idx}] '{outcome.label}' — price {outcome.price:.0%} > 30% threshold")
            continue

        edge     = abs(prob - outcome.price)
        bet_usdc = max(BET_SIZE_MIN, min(BET_SIZE_MAX, size))

        remaining = max_deploy - total_allocated
        if remaining < BET_SIZE_MIN:
            logger.info(f"  Budget exhausted after {len(results)} positions")
            break
        bet_usdc = min(bet_usdc, remaining)
        if bet_usdc < 1.0:
            logger.info(f"  Skipping [{idx}:{outcome_idx}] — bet_usdc ${bet_usdc:.2f} below $1 minimum")
            continue
        total_allocated += bet_usdc

        logger.info(
            f"    [{idx}:{outcome_idx}] '{outcome.label}'  '{market.question[:50]}'  "
            f"prob={prob:.0%}  mkt={outcome.price:.0%}  edge={edge:.0%}  ${bet_usdc:.2f}  — {reasoning[:80]}"
        )
        results.append((idx, Assessment(
            outcome_idx   = outcome_idx,
            outcome_label = outcome.label,
            price         = outcome.price,
            probability   = prob,
            edge          = edge,
            bet_usdc      = bet_usdc,
            reasoning     = reasoning,
        )))

    logger.info(f"  Total: {len(results)} positions  ${total_allocated:.2f} / ${max_deploy:.2f} budget")
    return results


# ── Order placement ────────────────────────────────────────────────────────────

def place_order(market: Market, assessment: Assessment) -> Optional[str]:
    """
    Place a limit buy order on Polymarket via py-clob-client.
    Returns order_id on success, None on failure.
    Returns a fake order_id in DRY_RUN mode without touching the exchange.
    """
    from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
    from py_clob_client.order_builder.constants import BUY

    outcome     = market.outcomes[assessment.outcome_idx]
    token_id    = outcome.token_id
    limit_price = round(min(outcome.price + 0.01, 0.96), 4)

    if DRY_RUN:
        order_id = f"DRY-{int(time.time())}"
        logger.info(
            f"  [DRY RUN] BUY '{outcome.label}'  '{market.question[:50]}'  "
            f"@ {limit_price:.3f}  ${assessment.bet_usdc:.2f} USDC"
        )
        return order_id

    try:
        clob        = _get_clob_client()
        min_shares  = max(1.0, market.min_size)
        size_shares = max(min_shares, math.ceil(assessment.bet_usdc / limit_price * 100) / 100)
        order       = clob.create_order(
            OrderArgs(token_id=token_id, price=limit_price, size=size_shares, side=BUY),
            options=PartialCreateOrderOptions(neg_risk=market.neg_risk),
        )
        logger.info(f"  create_order: token={token_id[:16]}… price={limit_price} size={size_shares} neg_risk={market.neg_risk}")
        result      = clob.post_order(order, OrderType.GTC)
        logger.info(f"  post_order response: {result}")

        if result and result.get("success"):
            return result.get("orderID") or result.get("order_id") or "unknown"
        logger.error(f"Order rejected by Polymarket: {result}")
        return None

    except Exception as e:
        logger.error(f"Order placement failed: {e}", exc_info=True)
        return None


# ── Main loop ──────────────────────────────────────────────────────────────────

def fetch_open_condition_ids() -> set[str]:
    """Fetch condition IDs that already have open orders on Polymarket."""
    if DRY_RUN:
        return set()
    try:
        clob   = _get_clob_client()
        orders = clob.get_orders()
        logger.info(f"  get_orders response: {orders}")
        return {o.get("conditionId") or o.get("asset_id", "") for o in (orders or []) if o}
    except Exception as e:
        logger.warning(f"Could not fetch open orders: {e}")
        return set()


def run_once(positions: dict[str, Position], balance_usdc: float) -> dict[str, Position]:
    """One scan cycle: fetch markets → batch Claude call → execute bets."""
    held_ids = set(positions.keys())
    logger.info(f"  Held positions: {len(held_ids)}")

    # Paginate until we have MAX_MARKETS_PER_LOOP candidates not already held
    candidates: list[tuple[Market, str]] = []
    offset = 0
    page_size = 100
    while len(candidates) < MAX_MARKETS_PER_LOOP:
        logger.info(f"── Fetching markets (offset={offset}) ──")
        markets, raw_count = fetch_markets(offset=offset, limit=page_size)
        if not markets and raw_count == 0:
            break
        new_markets = [m for m in markets if m.condition_id not in held_ids]
        skipped_held = len(markets) - len(new_markets)
        needed = MAX_MARKETS_PER_LOOP - len(candidates)
        new_markets = new_markets[:needed]
        logger.info(
            f"  Page offset={offset}: {len(markets)} eligible — "
            f"{skipped_held} skipped (already held) — "
            f"fetching news for {len(new_markets)}"
        )
        for market in new_markets:
            news = fetch_news(market.question)
            candidates.append((market, news))
        if raw_count < page_size:
            break  # no more pages
        offset += page_size

    if not CLAUDE_ENABLED:
        logger.info("── Claude disabled (CLAUDE_ENABLED=false) — skipping assessment ──")
        return positions

    logger.info(f"── Sending {len(candidates)} candidates to Claude (balance=${balance_usdc:.2f}) ──")
    bets = assess_markets_batch(candidates, balance_usdc, len(held_ids))

    for idx, assessed in bets:
        market = candidates[idx][0]

        logger.info(
            f"  → BET: '{assessed.outcome_label}'  '{market.question[:55]}'  "
            f"prob={assessed.probability:.0%}  edge={assessed.edge:.0%}  ${assessed.bet_usdc:.2f} USDC"
        )
        logger.info(f"     {assessed.reasoning}")

        order_id = place_order(market, assessed)
        if order_id is None:
            continue

        outcome  = market.outcomes[assessed.outcome_idx]
        position = Position(
            condition_id = market.condition_id,
            question     = market.question,
            outcome      = outcome.label,
            token_id     = outcome.token_id,
            entry_price  = outcome.price,
            size_usdc    = assessed.bet_usdc,
            order_id     = order_id,
            timestamp    = datetime.now(timezone.utc).isoformat(),
        )
        positions[market.condition_id] = position

        dry_tag = " [DRY RUN]" if DRY_RUN else ""
        send_telegram(
            f"🎯 <b>New Polymarket Bet{dry_tag}</b>\n"
            f"<b>Market:</b> {market.question}\n"
            f"<b>Closes:</b> {market.end_date}\n"
            f"<b>Bet:</b> {outcome.label} @ {outcome.price:.0%} "
            f"(pays {round(1/outcome.price, 1) if outcome.price > 0 else '?'}x)\n"
            f"<b>Size:</b> ${assessed.bet_usdc:.2f} USDC\n"
            f"<b>Claude prob:</b> {assessed.probability:.0%}  edge {assessed.edge:.0%}\n"
            f"<b>Why:</b> {assessed.reasoning}"
        )
        logger.info(f"     ✓ Order placed: {order_id}")
        time.sleep(1)

    return positions


def main() -> None:
    logger.info("═" * 60)
    logger.info("Polymarket Claude Bot — startup checks")
    logger.info("═" * 60)

    # 1. Verify Anthropic API key
    if not check_anthropic_connection():
        msg = "FATAL: Anthropic API check failed — check ANTHROPIC_API_KEY"
        logger.error(msg)
        send_telegram(f"🚨 {msg}")
        sys.exit(1)

    # 2. Approve exchange contracts (no-op if already approved)
    logger.info("Updating exchange allowances …")
    ensure_allowances()

    # 3. Fetch and verify USDC balance
    logger.info("Checking USDC balance …")
    balance = fetch_usdc_balance()
    if balance <= 0 and not DRY_RUN:
        msg = f"FATAL: USDC balance is ${balance:.2f} — fund the wallet before running live"
        logger.error(msg)
        send_telegram(f"🚨 {msg}")
        sys.exit(1)

    logger.info("═" * 60)
    logger.info(
        f"Bot ready  dry_run={DRY_RUN}  "
        f"balance=${balance:.2f}  "
        f"max_deploy={MAX_DEPLOY_FRACTION:.0%}/cycle  "
        f"min_edge={MIN_EDGE:.0%}  "
        f"interval={LOOP_INTERVAL_SECS}s"
    )
    logger.info("═" * 60)

    send_telegram(
        f"🤖 <b>Polymarket Claude Bot started</b>\n"
        f"dry_run={DRY_RUN}  balance=${balance:.2f}\n"
        f"max_deploy={MAX_DEPLOY_FRACTION:.0%}/cycle  "
        f"min_edge={MIN_EDGE:.0%}"
    )

    positions = load_positions()
    logger.info(f"Loaded {len(positions)} existing position(s)")

    while True:
        try:
            # Refresh balance and positions from API at start of each cycle
            balance   = fetch_usdc_balance()
            positions = load_positions()
            logger.info(f"Balance: ${balance:.2f} USDC  |  Positions: {len(positions)}")
            positions = run_once(positions, balance)
            save_positions(positions)
        except Exception as e:
            logger.error(f"Unhandled error in scan loop: {e}", exc_info=True)
            send_telegram(f"⚠️ Bot error: {e}")

        logger.info(f"Sleeping {LOOP_INTERVAL_SECS}s …\n")
        time.sleep(LOOP_INTERVAL_SECS)


if __name__ == "__main__":
    main()
