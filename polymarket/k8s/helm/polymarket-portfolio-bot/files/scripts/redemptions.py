"""
On-chain redemption of resolved Polymarket positions.
Ported from polymarket-btc-bot. Supports EOA (sig_type=0) and Gnosis Safe (sig_type=2).

Entry point: redeem_resolved_positions() — call before each trading cycle.
"""
from __future__ import annotations

import logging
import time

import requests

from config import (
    CHAIN_ID,
    CTF_CONTRACT,
    DATA_API,
    POLYGON_RPC,
    POLYMARKET_ADDRESS,
    POLYMARKET_FUNDER,
    POLYMARKET_PK,
    POLYMARKET_SIGNATURE_TYPE,
    USDC_ADDRESS,
)
from telegram import send_telegram

logger = logging.getLogger(__name__)
_warned_neg_risk_conditions: set[str] = set()


# ── Polygon RPC ───────────────────────────────────────────────────────────────

def _rpc(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    logger.info(f"  RPC → {method}  params={params}")
    resp = requests.post(POLYGON_RPC, json=payload, timeout=15)
    logger.info(f"  RPC ← status={resp.status_code}  body={resp.text[:300]}")
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def _erc1155_balance(token_id_str: str, address: str) -> int:
    import eth_abi
    from eth_utils import keccak, to_checksum_address
    selector = keccak(b"balanceOf(address,uint256)")[:4]
    calldata = "0x" + (selector + eth_abi.encode(
        ["address", "uint256"], [to_checksum_address(address), int(token_id_str)]
    )).hex()
    result  = _rpc("eth_call", [{"to": CTF_CONTRACT, "data": calldata}, "latest"])
    balance = int(result, 16)
    logger.info(f"  ERC-1155 balance  token={token_id_str[:16]}…  balance={balance}")
    return balance


# ── Data API ──────────────────────────────────────────────────────────────────

def _fetch_redeemable_positions() -> list:
    user = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
    if not user:
        logger.warning("  No wallet configured — cannot fetch redeemable positions")
        return []
    url    = f"{DATA_API}/positions"
    params = {"user": user, "redeemable": "true", "sizeThreshold": "0.01"}
    try:
        r = requests.get(url, params=params, timeout=15)
        logger.info(f"  data-api /positions redeemable=true  status={r.status_code}")
        r.raise_for_status()
        result = r.json()
        return result if isinstance(result, list) else []
    except Exception as exc:
        logger.warning(f"  data-api /positions error: {exc}")
        return []


# ── Transaction building ──────────────────────────────────────────────────────

def _build_redeem_calldata(condition_id_hex: str) -> str:
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address

    selector  = keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4]
    cid_bytes = bytes.fromhex(condition_id_hex.removeprefix("0x")).rjust(32, b"\x00")
    encoded_args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [to_checksum_address(USDC_ADDRESS), b"\x00" * 32, cid_bytes, [1, 2]],
    )
    return "0x" + (selector + encoded_args).hex()


def _send_tx(calldata: str, nonce: int, gas_price: int) -> str:
    from eth_utils import to_checksum_address
    from eth_account import Account
    account = Account.from_key(POLYMARKET_PK)
    tx = {
        "to": to_checksum_address(CTF_CONTRACT),
        "data": calldata,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 250_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])


def _send_tx_via_safe(calldata: str, to: str, nonce: int, gas_price: int) -> str:
    """Submit a call through the Gnosis Safe. Proxy wallet signs EIP-712 SafeTx."""
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address
    from eth_account import Account
    from eth_keys import keys as eth_keys_lib

    account    = Account.from_key(POLYMARKET_PK)
    safe       = to_checksum_address(POLYMARKET_FUNDER)
    to_addr    = to_checksum_address(to)
    data_bytes = bytes.fromhex(calldata.removeprefix("0x"))

    nonce_sel  = keccak(b"nonce()")[:4]
    raw_nonce  = _rpc("eth_call", [{"to": safe, "data": "0x" + nonce_sel.hex()}, "latest"])
    safe_nonce = int(raw_nonce, 16)

    DOMAIN_SEP_TYPEHASH = keccak(b"EIP712Domain(uint256 chainId,address verifyingContract)")
    SAFE_TX_TYPEHASH    = keccak(
        b"SafeTx(address to,uint256 value,bytes data,uint8 operation,"
        b"uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,"
        b"address refundReceiver,uint256 nonce)"
    )
    ZERO_ADDR = "0x0000000000000000000000000000000000000000"

    domain_sep = keccak(encode(
        ["bytes32", "uint256", "address"],
        [DOMAIN_SEP_TYPEHASH, CHAIN_ID, safe],
    ))
    safe_tx_hash = keccak(encode(
        ["bytes32", "address", "uint256", "bytes32", "uint8",
         "uint256", "uint256", "uint256", "address", "address", "uint256"],
        [SAFE_TX_TYPEHASH, to_addr, 0, keccak(data_bytes), 0,
         0, 0, 0, ZERO_ADDR, ZERO_ADDR, safe_nonce],
    ))
    msg_hash = keccak(b"\x19\x01" + domain_sep + safe_tx_hash)

    pk  = eth_keys_lib.PrivateKey(bytes.fromhex(POLYMARKET_PK.removeprefix("0x")))
    sig = pk.sign_msg_hash(msg_hash)
    signature = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v + 27])

    exec_sel  = keccak(b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)")[:4]
    exec_data = "0x" + (exec_sel + encode(
        ["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "bytes"],
        [to_addr, 0, data_bytes, 0, 0, 0, 0, ZERO_ADDR, ZERO_ADDR, signature],
    )).hex()

    tx = {
        "to": safe,
        "data": exec_data,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 300_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])


# ── Claim proxy → funder (Gnosis Safe only) ───────────────────────────────────

def _claim_to_funder() -> None:
    """Transfer proxy-wallet USDC.e to the funder. No-op if proxy is empty."""
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address
    from eth_account import Account

    account = Account.from_key(POLYMARKET_PK)
    usdc    = to_checksum_address(USDC_ADDRESS)
    funder  = to_checksum_address(POLYMARKET_FUNDER)

    bal_selector = keccak(b"balanceOf(address)")[:4]
    bal_data     = "0x" + (bal_selector + encode(["address"], [account.address])).hex()
    raw_bal      = _rpc("eth_call", [{"to": usdc, "data": bal_data}, "latest"])
    balance      = int(raw_bal, 16)

    if balance == 0:
        logger.info("  Claim: proxy wallet USDC.e balance is 0 — nothing to sweep")
        return

    usdc_amount = balance / 1_000_000
    logger.info(f"  Claim: sweeping {usdc_amount:.2f} USDC.e  proxy={account.address} → funder={funder}")

    transfer_selector = keccak(b"transfer(address,uint256)")[:4]
    transfer_data     = "0x" + (transfer_selector + encode(
        ["address", "uint256"], [funder, balance]
    )).hex()

    nonce     = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)

    tx = {
        "to": usdc,
        "data": transfer_data,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 100_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed  = account.sign_transaction(tx)
    raw     = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
    logger.info(f"  Claim tx: {tx_hash}  amount={usdc_amount:.2f} USDC.e")
    send_telegram(f"🏦 <b>Claimed</b>\n{usdc_amount:.2f} USDC.e → funder\ntx: {tx_hash}")


# ── Public entry point ────────────────────────────────────────────────────────

def redeem_resolved_positions() -> None:
    """
    Claim every redeemable position on-chain.
    Call once per cycle, before Claude sees the position set.
    Safe to call every cycle — no-ops if nothing is redeemable.
    """
    from eth_account import Account

    if not POLYMARKET_PK:
        logger.info("  redeem: POLYMARKET_PK unset — skipping")
        return

    positions = _fetch_redeemable_positions()
    logger.info(f"  redeem: {len(positions)} redeemable position(s)")
    if not positions:
        return

    to_redeem = []
    rpc_failures = 0
    last_rpc_error = ""
    for pos in positions:
        condition_id = pos.get("conditionId", "")
        token_id     = pos.get("asset", "")
        question     = pos.get("title", condition_id[:16])
        negative_risk = bool(pos.get("negativeRisk") or pos.get("negRisk") or False)

        if not condition_id or not token_id:
            logger.warning(f"  redeem: missing conditionId/asset on {pos}")
            continue

        # Negative-risk markets settle through a different path than the plain
        # CTF redeemPositions(..., [1, 2]) flow used by the BTC bot. Replaying
        # this calldata on neg-risk positions burns gas but does not clear the
        # ERC-1155 balance, so skip and alert once instead of retrying forever.
        if negative_risk:
            logger.warning(
                "  redeem: skipping neg-risk position  cid=%s  question='%s'",
                condition_id[:16], question[:60],
            )
            if condition_id not in _warned_neg_risk_conditions:
                _warned_neg_risk_conditions.add(condition_id)
                send_telegram(
                    f"⚠️ <b>Redeem skipped</b>\n"
                    f"Negative-risk market requires a different redemption path.\n"
                    f"{question[:120]}"
                )
            continue

        try:
            holder  = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
            balance = _erc1155_balance(token_id, holder)
        except Exception as exc:
            rpc_failures += 1
            last_rpc_error = str(exc)
            logger.warning(f"  redeem: balance check failed for {condition_id[:16]}: {exc}")
            continue

        if balance <= 0:
            logger.info(f"  redeem: no on-chain balance for {condition_id[:16]} — skipping")
            continue

        to_redeem.append((condition_id, question))

    # If every balance check failed, the RPC is broken — alert loudly. Without this
    # the bot silently stops claiming capital for days (see 2026-04-15 Ankr outage).
    if rpc_failures and rpc_failures == len(positions):
        logger.error(f"  redeem: ALL {rpc_failures} RPC balance checks failed — RPC is broken")
        send_telegram(
            f"🚨 <b>Redemption RPC down</b>\n"
            f"All {rpc_failures} balance checks failed.\n"
            f"Error: {last_rpc_error[:200]}\n"
            f"Redeemable positions will stay locked until fixed."
        )
        return

    if not to_redeem:
        logger.info("  redeem: nothing with on-chain balance to redeem")
        return

    account   = Account.from_key(POLYMARKET_PK)
    nonce     = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)

    # Polygon's Bor node caps concurrent in-flight txs per delegated (Safe-proxy)
    # sender. Firing 20+ SafeTx back-to-back trips "in-flight transaction limit
    # reached" or "gapped-nonce" errors. Space them out + retry on those errors.
    INTER_TX_SLEEP = 6.0
    RETRY_SLEEP    = 15.0

    def _send_one(cid: str, q: str, current_nonce: int) -> tuple[bool, int]:
        calldata = _build_redeem_calldata(cid)
        if POLYMARKET_SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER:
            tx_hash = _send_tx_via_safe(calldata, CTF_CONTRACT, current_nonce, gas_price)
        else:
            tx_hash = _send_tx(calldata, current_nonce, gas_price)
        logger.info(f"  redeem ✓ tx={tx_hash}  '{q[:40]}'")
        send_telegram(f"💰 <b>Redeemed</b>\n{q[:80]}\ntx: {tx_hash}")
        return True, current_nonce + 1

    for idx, (condition_id, question) in enumerate(to_redeem):
        if idx > 0:
            time.sleep(INTER_TX_SLEEP)
        logger.info(f"  redeem → '{question[:60]}'  cid={condition_id[:16]}…")
        try:
            _, nonce = _send_one(condition_id, question, nonce)
        except Exception as exc:
            err = str(exc)
            if "nonce too low" in err or "already known" in err:
                logger.info(f"  redeem: already redeemed externally: '{question[:40]}'")
                nonce += 1
                continue
            if "in-flight transaction limit" in err or "gapped-nonce" in err:
                logger.warning(f"  redeem: Polygon in-flight cap hit — sleeping {RETRY_SLEEP}s and retrying")
                time.sleep(RETRY_SLEEP)
                try:
                    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
                    _, nonce = _send_one(condition_id, question, nonce)
                    continue
                except Exception as exc2:
                    err2 = str(exc2)
                    if "nonce too low" in err2 or "already known" in err2:
                        logger.info(f"  redeem: already redeemed externally (retry): '{question[:40]}'")
                        nonce += 1
                        continue
                    logger.error(f"  redeem retry failed for '{question[:40]}': {exc2}")
                    continue
            logger.error(f"  redeem failed for '{question[:40]}': {exc}")

    if POLYMARKET_FUNDER:
        try:
            _claim_to_funder()
        except Exception as exc:
            logger.error(f"  claim_to_funder failed: {exc}")
