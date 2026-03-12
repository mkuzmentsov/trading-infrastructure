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
DRY_RUN                   = os.environ.get("DRY_RUN", "true").lower() == "true"
MIN_MARKET_VOLUME         = float(os.environ.get("MIN_MARKET_VOLUME", "50000"))
MIN_EDGE                  = float(os.environ.get("MIN_EDGE", "0.05"))
MAX_DEPLOY_FRACTION       = float(os.environ.get("MAX_DEPLOY_FRACTION", "0.20"))
MAX_MARKETS_PER_LOOP      = int(os.environ.get("MAX_MARKETS_PER_LOOP", "40"))
BET_SIZE_MIN              = float(os.environ.get("BET_SIZE_MIN", "4"))
BET_SIZE_MAX              = float(os.environ.get("BET_SIZE_MAX", "25"))
LOOP_INTERVAL_SECS        = int(os.environ.get("LOOP_INTERVAL_SECS", "600"))
TELEGRAM_TOKEN            = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID          = os.environ.get("TELEGRAM_CHAT_ID", "")
DATA_DIR                  = Path(os.environ.get("DATA_DIR", "/app/data"))

GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
CHAIN_ID   = 137   # Polygon mainnet

# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Market:
    condition_id:  str
    question:      str
    description:   str
    yes_price:     float   # 0–1, market-implied YES probability
    no_price:      float
    volume_24h:    float
    volume_total:  float
    end_date:      str
    yes_token_id:  str
    no_token_id:   str


@dataclass
class Assessment:
    action:      str    # BUY_YES | BUY_NO
    probability: float  # Claude's YES probability estimate
    confidence:  str    # low | medium | high
    edge:        float  # |Claude prob − market price|
    bet_usdc:    float  # amount Claude decided to bet
    reasoning:   str


@dataclass
class Position:
    condition_id: str
    question:     str
    side:         str    # YES | NO
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
    p = _positions_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
        return {k: Position(**v) for k, v in raw.items()}
    except Exception as e:
        logger.warning(f"Could not load positions: {e}")
        return {}


def save_positions(positions: dict[str, Position]) -> None:
    _positions_path().write_text(
        json.dumps({k: asdict(v) for k, v in positions.items()}, indent=2)
    )


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
    """
    Return an initialised ClobClient with API credentials.
    If API key/secret/passphrase are not provided, auto-generates them from
    the private key and caches them to DATA_DIR/api_creds.json for reuse.
    """
    global _cached_clob_client
    if _cached_clob_client is not None:
        return _cached_clob_client

    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    # Build client with private key (L1 only at this point)
    client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=POLYMARKET_PK,
        signature_type=POLYMARKET_SIGNATURE_TYPE,
    )

    # Use provided credentials, load from cache, or auto-generate
    if POLYMARKET_API_KEY and POLYMARKET_API_SECRET and POLYMARKET_API_PASSPHRASE:
        creds = ApiCreds(
            api_key=POLYMARKET_API_KEY,
            api_secret=POLYMARKET_API_SECRET,
            api_passphrase=POLYMARKET_API_PASSPHRASE,
        )
        logger.info("  Using API credentials from config")
    else:
        creds_path = DATA_DIR / "api_creds.json"
        if creds_path.exists():
            d = json.loads(creds_path.read_text())
            creds = ApiCreds(
                api_key=d["api_key"],
                api_secret=d["api_secret"],
                api_passphrase=d["api_passphrase"],
            )
            logger.info("  Using cached API credentials")
        else:
            logger.info("  Generating API credentials from private key …")
            for nonce in range(10):
                try:
                    creds = client.create_api_key(nonce=nonce)
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    creds_path.write_text(json.dumps({
                        "api_key":        creds.api_key,
                        "api_secret":     creds.api_secret,
                        "api_passphrase": creds.api_passphrase,
                    }))
                    logger.info(f"  Generated API credentials (nonce={nonce})")
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError("Failed to generate API credentials for all nonces 0-4")

    client.set_api_creds(creds)
    _cached_clob_client = client
    return client


def ensure_allowances() -> None:
    """Approve Polymarket exchange contracts to spend USDC (one-time setup)."""
    if DRY_RUN:
        return
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = _get_clob_client()
        clob.update_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        logger.info("  Exchange contracts approved for USDC spending")
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
        bal  = float(data.get("balance", 0)) / 1_000_000  # USDC has 6 decimals
        logger.info(f"  Balance: ${bal:.2f} USDC")
        return bal
    except Exception as e:
        logger.warning(f"  Balance check failed: {e}")
        return 0.0


# ── Market data ────────────────────────────────────────────────────────────────

def fetch_markets() -> list[Market]:
    """Fetch active binary markets from Polymarket Gamma API, sorted by 24h volume."""
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "closed": "false", "limit": 100,
                    "order": "volume24hr", "ascending": "false"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch markets: {e}")
        return []

    now = datetime.now(timezone.utc)
    markets: list[Market] = []
    raw = resp.json()
    skipped_binary = skipped_price = skipped_vol = skipped_expiry = 0

    # Log one raw market so we can inspect the field structure if needed
    if raw:
        sample = raw[0]
        logger.debug(f"Sample market fields: {list(sample.keys())}")
        logger.debug(f"Sample outcomes={sample.get('outcomes')} clobTokenIds={sample.get('clobTokenIds')}")

    for m in raw:
        try:
            # Require exactly 2 CLOB token IDs (YES and NO tokens) — this is the
            # trading requirement. Multi-outcome and non-CLOB markets won't have them.
            token_ids = m.get("clobTokenIds") or []
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if len(token_ids) < 2:
                skipped_binary += 1
                continue

            prices_raw = m.get("outcomePrices", ["0.5", "0.5"])
            if isinstance(prices_raw, str):
                prices_raw = json.loads(prices_raw)
            yes_price = float(prices_raw[0])
            no_price  = float(prices_raw[1])

            if yes_price < 0.005 or yes_price > 0.995:
                skipped_price += 1
                continue

            # volume24hr field name varies across API versions
            vol_24h = float(m.get("volume24hr") or m.get("volume24Hr") or m.get("volumeNum") or 0)
            if vol_24h < MIN_MARKET_VOLUME:
                skipped_vol += 1
                continue

            # Skip markets closing in < 24h
            end_date_str = m.get("endDate", "")
            if end_date_str:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if (end_dt - now).total_seconds() < 86400:
                    skipped_expiry += 1
                    continue

            markets.append(Market(
                condition_id  = m.get("conditionId") or m.get("id", ""),
                question      = m.get("question", ""),
                description   = (m.get("description") or "")[:500],
                yes_price     = yes_price,
                no_price      = no_price,
                volume_24h    = vol_24h,
                volume_total  = float(m.get("volume") or 0),
                end_date      = end_date_str,
                yes_token_id  = str(token_ids[0]),
                no_token_id   = str(token_ids[1]),
            ))
        except Exception as e:
            logger.warning(f"Skipping market (parse error): {e}")

    logger.info(
        f"  Fetched {len(raw)} markets — kept {len(markets)} "
        f"(skipped: non-binary={skipped_binary} price={skipped_price} "
        f"vol={skipped_vol} expiry={skipped_expiry})"
    )
    return markets


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
        yes_mult = round(1 / market.yes_price, 1) if market.yes_price > 0 else 0
        no_mult  = round(1 / market.no_price,  1) if market.no_price  > 0 else 0
        section  = (
            f"[{idx}] {market.question}\n"
            f"    Resolves: {market.end_date} | Vol: ${market.volume_24h:,.0f}\n"
            f"    YES {market.yes_price:.1%} ({yes_mult}x) | NO {market.no_price:.1%} ({no_mult}x)\n"
            f"    {market.description[:200] if market.description else ''}"
            + (f"\n    News: {news[:300]}" if news else "")
        )
        market_sections.append(section)

    prompt = f"""Today is {today}. You are a prediction market analyst.

Analyze the {len(candidates)} markets below and output trading signals.
Budget: ${max_deploy:.2f} USDC total. Each position: ${BET_SIZE_MIN:.2f}–${BET_SIZE_MAX:.2f} USDC.

Strategy: high-variance positive-EV — many small bets on mispriced markets.
Most bets lose; a 2% market pays 50x when correct. Target 10–20 positions per cycle.

For each market where you have an edge, include it in the JSON output.
Scale size by confidence: ${BET_SIZE_MAX:.2f} = high confidence, $1 = speculative.

MARKETS:
{chr(10).join(market_sections)}

Respond with ONLY a JSON array, no other text. Example format:
[
  {{"i": 3, "action": "BUY_NO", "prob_yes": 0.02, "size": 5.0, "why": "reason"}},
  {{"i": 7, "action": "BUY_YES", "prob_yes": 0.15, "size": 1.0, "why": "reason"}}
]
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
        match = re.search(r'\[.*\]', text, re.DOTALL)
        raw_bets = json.loads(match.group()) if match else []
    except Exception as e:
        logger.error(f"Failed to parse Claude JSON: {e}\nRaw: {text[:300]}")
        return []

    logger.info(f"  Claude returned {len(raw_bets)} position(s)")

    results: list[tuple[int, Assessment]] = []
    total_allocated = 0.0

    for bet in raw_bets:
        try:
            idx       = int(bet["i"])
            action    = bet["action"]
            prob      = float(bet["prob_yes"])
            size      = float(bet["size"])
            reasoning = bet.get("why", "")
        except (KeyError, ValueError) as e:
            logger.warning(f"  Skipping malformed bet {bet}: {e}")
            continue

        if idx < 0 or idx >= len(candidates):
            logger.warning(f"  Invalid market index {idx} — skip")
            continue

        market   = candidates[idx][0] if isinstance(candidates[idx], tuple) else candidates[idx]
        edge     = abs(prob - market.yes_price)
        bet_usdc = max(BET_SIZE_MIN, min(BET_SIZE_MAX, size))

        remaining = max_deploy - total_allocated
        if remaining < BET_SIZE_MIN:
            logger.info(f"  Budget exhausted after {len(results)} positions")
            break
        bet_usdc = min(bet_usdc, remaining)
        total_allocated += bet_usdc

        logger.info(
            f"    [{idx}] {action}  '{market.question[:60]}'  "
            f"prob={prob:.0%}  edge={edge:.0%}  ${bet_usdc:.2f}  — {reasoning[:100]}"
        )
        results.append((idx, Assessment(
            action=action,
            probability=prob,
            confidence="medium",
            edge=edge,
            bet_usdc=bet_usdc,
            reasoning=reasoning,
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
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    buying_yes   = assessment.action == "BUY_YES"
    side_label   = "YES" if buying_yes else "NO"
    token_id     = market.yes_token_id if buying_yes else market.no_token_id
    market_price = market.yes_price if buying_yes else market.no_price
    limit_price  = round(min(market_price + 0.01, 0.96), 4)

    if DRY_RUN:
        order_id = f"DRY-{int(time.time())}"
        logger.info(
            f"  [DRY RUN] BUY {side_label}  '{market.question[:55]}'  "
            f"@ {limit_price:.3f}  ${assessment.bet_usdc:.2f} USDC"
        )
        return order_id

    try:
        clob        = _get_clob_client()
        size_shares = round(assessment.bet_usdc / limit_price, 2)
        order       = clob.create_order(OrderArgs(token_id=token_id, price=limit_price,
                                                  size=size_shares, side=BUY))
        result      = clob.post_order(order, OrderType.GTC)

        if result and result.get("success"):
            return result.get("orderID") or result.get("order_id") or "unknown"
        logger.error(f"Order rejected by Polymarket: {result}")
        return None

    except Exception as e:
        logger.error(f"Order placement failed: {e}", exc_info=True)
        return None


# ── Main loop ──────────────────────────────────────────────────────────────────

def run_once(positions: dict[str, Position], balance_usdc: float) -> dict[str, Position]:
    """One scan cycle: fetch markets → gather news → batch Claude call → execute bets."""
    logger.info("── Fetching markets ──────────────────────────────────────────")
    markets = fetch_markets()
    logger.info(f"  {len(markets)} eligible markets (vol≥${MIN_MARKET_VOLUME:,.0f}, binary, >48h)")

    held_ids = set(positions.keys())

    # Build candidate list: markets not already held
    candidates: list[tuple[Market, str]] = []
    for market in markets:
        if len(candidates) >= MAX_MARKETS_PER_LOOP:
            break
        if market.condition_id in held_ids:
            continue
        logger.info(f"  Fetching news: {market.question[:65]}")
        news = fetch_news(market.question)
        candidates.append((market, news))
        time.sleep(0.3)  # DuckDuckGo rate-limit politeness

    logger.info(f"── Sending {len(candidates)} candidates to Claude (balance=${balance_usdc:.2f}) ──")
    bets = assess_markets_batch(candidates, balance_usdc, len(held_ids))

    for idx, assessed in bets:
        market = candidates[idx][0]
        buying_yes = assessed.action == "BUY_YES"

        logger.info(
            f"  → BET: {assessed.action}  '{market.question[:60]}'  "
            f"prob={assessed.probability:.0%}  edge={assessed.edge:.0%}  "
            f"conf={assessed.confidence}  ${assessed.bet_usdc:.2f} USDC"
        )
        logger.info(f"     {assessed.reasoning}")

        order_id = place_order(market, assessed)
        if order_id is None:
            continue

        position = Position(
            condition_id = market.condition_id,
            question     = market.question,
            side         = "YES" if buying_yes else "NO",
            token_id     = market.yes_token_id if buying_yes else market.no_token_id,
            entry_price  = market.yes_price if buying_yes else market.no_price,
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
            f"<b>Bet:</b> BUY {'YES' if buying_yes else 'NO'} "
            f"@ {position.entry_price:.0%}\n"
            f"<b>Size:</b> ${assessed.bet_usdc:.2f} USDC\n"
            f"<b>Claude prob:</b> {assessed.probability:.0%} YES "
            f"(edge {assessed.edge:.0%})\n"
            f"<b>Confidence:</b> {assessed.confidence}\n"
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
            # Refresh balance at start of each cycle
            balance = fetch_usdc_balance()
            logger.info(f"Balance: ${balance:.2f} USDC")
            positions = run_once(positions, balance)
            save_positions(positions)
        except Exception as e:
            logger.error(f"Unhandled error in scan loop: {e}", exc_info=True)
            send_telegram(f"⚠️ Bot error: {e}")

        logger.info(f"Sleeping {LOOP_INTERVAL_SECS}s …\n")
        time.sleep(LOOP_INTERVAL_SECS)


if __name__ == "__main__":
    main()
