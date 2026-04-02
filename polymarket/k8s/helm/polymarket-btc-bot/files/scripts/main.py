"""
Polymarket BTC direction bot — entry point.

Strategy:
  1. Fetch live BTC/USDT 5-min OHLCV from Binance (via ccxt).
  2. Compute the same 107 features as generate_features.py.
  3. Run a pre-trained LightGBM model → P(BTC UP in N minutes).
  4. Scan Polymarket for active BTC price-direction markets.
  5. Bet small amounts whenever model edge > MIN_EDGE.
  6. Size via quarter-Kelly, capped at BET_SIZE_MAX.

Environment variables (injected by K8s Secret):
  MODEL_PATH            path to LightGBM .txt model (default /app/data/model.txt)
  DRY_RUN               "true" / "false"
  MIN_EDGE              min edge to bet (default 0.05 = 5pp)
  BET_SIZE_MIN          min bet in USDC (default 0.50)
  BET_SIZE_MAX          max bet in USDC (default 5.00)
  LOOP_INTERVAL_SECS    seconds between cycles (default 300)
  POLYMARKET_PK         hex private key
  POLYMARKET_ADDRESS    wallet address
  POLYMARKET_API_KEY / _SECRET / _PASSPHRASE
  POLYMARKET_SIGNATURE_TYPE  0=EOA, 2=Gnosis Safe
  POLYMARKET_FUNDER     Safe address (if type=2)
  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
  DATA_DIR              persistent data directory (default /app/data)
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from clob import build_clob_client, fetch_usdc_balance, has_trade_on_market, kelly_size, place_bet
from config import (
    BET_SIZE_MIN, DRY_RUN, LOOP_INTERVAL, MIN_EDGE,
    MODEL_PATH, POLYMARKET_ADDRESS, POLYMARKET_PK, log,
)
from features import compute_features
from gamma import compute_edge, fetch_btc_5m_market, get_up_down_tokens
from market_data import fetch_btc_ohlcv
from model import load_model, predict_up_probability
from redemptions import redeem_resolved_positions
from telegram import tg


def _run_redemption(clob) -> None:  # noqa: ARG001
    if DRY_RUN:
        return
    try:
        redeem_resolved_positions()
    except Exception as exc:
        log.error("Redemption sweep failed: %s", exc)


def run_cycle(clob) -> None:
    cycle_start = time.time()
    log.info("── Cycle start ─────────────────────────────")

    # 1. Fetch live BTC data and compute features
    try:
        ohlcv = fetch_btc_ohlcv()
    except Exception as exc:
        log.error("Failed to fetch OHLCV: %s", exc)
        return

    btc_price = float(ohlcv["close"].iloc[-1])
    log.info("BTC price: $%.2f", btc_price)

    try:
        features = compute_features(ohlcv)
    except Exception as exc:
        log.error("Feature computation failed: %s", exc)
        return

    # 2. Model prediction
    p_up = predict_up_probability(features)
    log.info("P(UP 5m) = %.3f  P(DOWN) = %.3f", p_up, 1 - p_up)

    # No strong signal → skip
    confidence = abs(p_up - 0.5) * 2
    if confidence < 0.10:
        log.info("Low confidence (%.2f) — skipping cycle", confidence)
        _run_redemption(clob)
        return

    # 3. Fetch balance (drives true Kelly sizing)
    balance = fetch_usdc_balance(clob)
    if balance < BET_SIZE_MIN and not DRY_RUN:
        log.warning("Balance $%.2f below minimum bet — skipping cycle", balance)
        _run_redemption(clob)
        return

    # 4. Fetch the current BTC Up/Down 5-min market by slug
    try:
        market = fetch_btc_5m_market()
    except Exception as exc:
        log.error("Failed to fetch market: %s", exc)
        _run_redemption(clob)
        return

    if market is None:
        log.info("No active btc-updown-5m market found — skipping cycle")
        _run_redemption(clob)
        return

    condition_id = market.get("conditionId") or market.get("condition_id", "")
    question     = market.get("question", "")

    if not DRY_RUN and has_trade_on_market(clob, condition_id):
        log.info("Already bet on this market (%s) — skipping", question[:60])
        elapsed = time.time() - cycle_start
        log.info("── Cycle done in %.1fs ─────────────────────", elapsed)
        _run_redemption(clob)
        return

    up_token, down_token = get_up_down_tokens(market)
    if up_token is None or down_token is None:
        log.warning("Could not identify Up/Down tokens in market: %s", market)
        _run_redemption(clob)
        return

    up_price   = float(up_token.get("price",   0.5))
    down_price = float(down_token.get("price", 0.5))

    edge_up   = compute_edge(p_up, up_price,   "up")
    edge_down = compute_edge(p_up, down_price, "down")
    log.info(
        "Market: %s | up_p=%.3f down_p=%.3f | edge_up=%.3f edge_down=%.3f",
        question[:70], up_price, down_price, edge_up, edge_down,
    )

    if edge_up >= edge_down and edge_up >= MIN_EDGE:
        direction, token, price, edge = "up",   up_token,   up_price,   edge_up
    elif edge_down > edge_up and edge_down >= MIN_EDGE:
        direction, token, price, edge = "down", down_token, down_price, edge_down
    else:
        log.info("No edge above %.2f on either side — skipping", MIN_EDGE)
        elapsed = time.time() - cycle_start
        log.info("── Cycle done in %.1fs ─────────────────────", elapsed)
        _run_redemption(clob)
        return

    size    = kelly_size(edge, price, balance)
    p_model = p_up if direction == "up" else 1.0 - p_up
    log.info(
        "BET | %s | p_model=%.3f p_mkt=%.3f edge=%.3f size=$%.2f",
        direction.upper(), p_model, price, edge, size,
    )

    bets_placed = 0
    if DRY_RUN:
        log.info("  DRY_RUN — would bet %s $%.2f on %s", direction.upper(), size, question[:60])
    else:
        order_id = place_bet(clob, token, size, condition_id, int(market.get("takerBaseFee", 0)))
        if order_id:
            log.info("  Placed order %s", order_id)
            tg(
                f"🎯 <b>BTC 5m Bet</b>\n"
                f"Market: {question[:80]}\n"
                f"Direction: {direction.upper()}\n"
                f"P(model)={p_model:.2%}  P(market)={price:.2%}  edge={edge:.2%}\n"
                f"Size: ${size:.2f}  |  Order: {order_id}"
            )
            bets_placed += 1

    elapsed = time.time() - cycle_start
    log.info("── Cycle done in %.1fs | bets=%d ─────────────", elapsed, bets_placed)
    _run_redemption(clob)


def main() -> None:
    log.info("=" * 60)
    log.info("Polymarket BTC Bot starting")
    log.info("  DRY_RUN=%s  MIN_EDGE=%.2f  BET=[%.2f, %.2f]  LOOP=%ds",
             DRY_RUN, MIN_EDGE, BET_SIZE_MIN, BET_SIZE_MIN, LOOP_INTERVAL)
    log.info("  MODEL_PATH=%s", MODEL_PATH)
    log.info("=" * 60)

    if not POLYMARKET_PK and not DRY_RUN:
        raise RuntimeError("POLYMARKET_PK not set and DRY_RUN=false — refusing to start")

    load_model()

    clob = None
    if not DRY_RUN:
        try:
            clob = build_clob_client()
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            bal_data = clob.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            bal = float(bal_data.get("balance", 0)) / 1_000_000
            log.info("Wallet %s  balance: %.2f USDC", POLYMARKET_ADDRESS, bal)
        except Exception as exc:
            log.error("CLOB client init failed: %s", exc)
            if not DRY_RUN:
                raise

    def sleep_until_next_boundary() -> None:
        now           = time.time()
        next_boundary = math.ceil(now / LOOP_INTERVAL) * LOOP_INTERVAL
        wait          = next_boundary - now
        next_dt       = datetime.fromtimestamp(next_boundary, tz=timezone.utc)
        log.info("Sleeping %.1fs until next boundary %s …", wait, next_dt.strftime("%H:%M:%S UTC"))
        time.sleep(wait)

    sleep_until_next_boundary()

    while True:
        try:
            run_cycle(clob)
        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception as exc:
            log.exception("Unhandled error in cycle: %s", exc)

        sleep_until_next_boundary()


if __name__ == "__main__":
    main()
