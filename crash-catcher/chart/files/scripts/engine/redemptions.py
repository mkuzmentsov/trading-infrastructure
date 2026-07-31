"""
On-chain redemption: checks resolved Polymarket positions and redeems them via Polygon RPC.
Supports both EOA (SIGNATURE_TYPE=0) and Gnosis Safe (SIGNATURE_TYPE=2) wallets.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import eth_abi
import requests

from config import (
    CHAIN_ID, CTF_CONTRACT, DATA_API, POLYGON_RPC,
    POLYMARKET_ADDRESS, POLYMARKET_FUNDER, POLYMARKET_PK,
    SIGNATURE_TYPE, USDC_ADDRESS, USE_RELAYER, log,
)
from core.positions import Position, pos_store


_redeemed_conditions: set[str] = set()


# ── Polygon RPC ───────────────────────────────────────────────────────────────

def _rpc(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    log.info("Polygon RPC REQUEST  method=%s  params=%s", method, params)
    resp = requests.post(POLYGON_RPC, json=payload, timeout=15)
    log.info("Polygon RPC RESPONSE  status=%d  body=%s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def _erc1155_balance(token_id_str: str, address: str) -> int:
    from eth_utils import keccak, to_checksum_address
    selector = keccak(b"balanceOf(address,uint256)")[:4]
    calldata = "0x" + (selector + eth_abi.encode(
        ["address", "uint256"], [to_checksum_address(address), int(token_id_str)]
    )).hex()
    log.info(
        "ERC-1155 balanceOf REQUEST  contract=%s  token_id=%s  address=%s",
        CTF_CONTRACT, token_id_str, address,
    )
    result  = _rpc("eth_call", [{"to": CTF_CONTRACT, "data": calldata}, "latest"])
    balance = int(result, 16)
    log.info("ERC-1155 balanceOf RESPONSE  token_id=%s  balance=%d", token_id_str, balance)
    return balance


# ── Data API ──────────────────────────────────────────────────────────────────

def _fetch_redeemable_positions() -> list:
    """Fetch positions with redeemable=true from the Data API."""
    url    = f"{DATA_API}/positions"
    user   = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
    params = {"user": user, "redeemable": "true", "sizeThreshold": "0.01"}
    log.info("Data API positions REQUEST  url=%s  params=%s", url, params)
    try:
        r = requests.get(url, params=params, timeout=15)
        log.info("Data API positions RESPONSE  status=%d  body=%s", r.status_code, r.text[:1000])
        r.raise_for_status()
        result = r.json()
        if not isinstance(result, list):
            result = []
        return result
    except Exception as exc:
        log.warning("Data API positions ERROR: %s", exc)
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
    """Submit a call through the Gnosis Safe (SIGNATURE_TYPE=2).

    The proxy wallet (POLYMARKET_ADDRESS) is the sole Safe owner and signs the
    EIP-712 SafeTx hash, then sends execTransaction to the Safe contract.
    """
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


# ── Claim proxy → funder ──────────────────────────────────────────────────────

def _claim_to_funder() -> None:
    """
    Transfer all USDC.e from the proxy wallet (POLYMARKET_ADDRESS) to the funder (POLYMARKET_FUNDER).
    Only relevant for Gnosis Safe setup (SIGNATURE_TYPE=2).
    """
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
        log.info("Claim: proxy wallet USDC.e balance is 0 — nothing to claim")
        return

    usdc_amount = balance / 1_000_000
    log.info("Claiming %.2f USDC.e from proxy %s → funder %s", usdc_amount, account.address, funder)

    transfer_selector = keccak(b"transfer(address,uint256)")[:4]
    transfer_data     = "0x" + (transfer_selector + encode(["address", "uint256"], [funder, balance])).hex()

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
    log.info("Claim tx sent: %s  (%.2f USDC.e)", tx_hash, usdc_amount)


# ── Public entry point ────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _emit_redemption_event(
    on_event: Optional[Callable[..., None]],
    payload: dict,
    tracked_pos: Optional[Position],
    tx_hash: str,
) -> None:
    if on_event is None:
        return

    size = _safe_float(payload.get("size"))
    current_value = _safe_float(payload.get("currentValue"))
    avg_price = _safe_float(payload.get("avgPrice"))
    entry_price = tracked_pos.entry_price if tracked_pos else avg_price
    shares = size if size > 0 else float(tracked_pos.shares if tracked_pos else 0)
    exit_price = (current_value / shares) if shares > 0 else 0.0
    pnl = round(current_value - (shares * entry_price), 2)
    won = exit_price >= 0.99

    on_event(
        "position_closed",
        condition_id=payload.get("conditionId", ""),
        question=payload.get("title", ""),
        market_start_ts=None,
        market_end_ts=None,
        seconds_left=0,
        direction=(tracked_pos.direction if tracked_pos else str(payload.get("outcome", "")).upper()),
        token_id=payload.get("asset", ""),
        shares=round(shares, 6),
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        pnl=pnl,
        reason="redemption_win" if won else "redemption_loss",
        dry_run=False,
        order_id=tx_hash,
        resolution_source="redemption",
        tracked_position=tracked_pos is not None,
        redeemable_size=round(size, 6),
        redeemable_avg_price=round(avg_price, 4),
        redeemable_current_value=round(current_value, 4),
        redeemable_cash_pnl=round(_safe_float(payload.get("cashPnl")), 4),
        redeemable_realized_pnl=round(_safe_float(payload.get("realizedPnl")), 4),
    )


def redeem_resolved_positions(on_event: Optional[Callable[..., None]] = None) -> None:
    """
    Check redeemable positions via the Data API.
    For each position with an on-chain token balance, call redeemPositions.
    Fetches nonce once and increments per tx to avoid collisions.
    """
    from eth_account import Account

    positions = _fetch_redeemable_positions()
    if not positions:
        log.info("No redeemable positions found")
        return

    to_redeem = []
    for pos in positions:
        condition_id = pos.get("conditionId", "")
        token_id     = pos.get("asset", "")
        question     = pos.get("title", condition_id[:16])

        if not condition_id or not token_id:
            log.warning("Position missing conditionId or asset: %s", pos)
            continue
        if condition_id in _redeemed_conditions:
            log.info("Condition already processed for redemption: %s", condition_id[:16])
            continue

        try:
            holder  = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
            balance = _erc1155_balance(token_id, holder)
        except Exception as exc:
            log.warning("Could not check ERC-1155 balance for %s: %s", condition_id[:16], exc)
            continue

        if balance <= 0:
            log.info("No on-chain token balance for %s — skipping", condition_id[:16])
            continue

        to_redeem.append((condition_id, question, token_id, pos))

    if not to_redeem:
        return

    # Relayer path (gasless) fetches its own Safe nonce per tx; the account
    # nonce / gas price are only needed for the self-broadcast RPC fallback.
    use_relayer = USE_RELAYER and SIGNATURE_TYPE == 2 and bool(POLYMARKET_FUNDER)
    account = Account.from_key(POLYMARKET_PK)
    nonce = gas_price = 0
    if not use_relayer:
        nonce     = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
        gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)
    if use_relayer:
        log.info("Redemption submission via Polymarket relayer (gasless, Safe)")

    for condition_id, question, token_id, payload in to_redeem:
        log.info("Market resolved, redeeming: %s", question[:60])
        try:
            calldata = _build_redeem_calldata(condition_id)
            if use_relayer:
                from engine.relayer import submit_and_wait
                tx_hash = submit_and_wait(CTF_CONTRACT, calldata)
            elif SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER:
                tx_hash = _send_tx_via_safe(calldata, CTF_CONTRACT, nonce, gas_price)
            else:
                tx_hash = _send_tx(calldata, nonce, gas_price)
            log.info("Redeemed %s  tx=%s", question[:40], tx_hash)
            tracked_pos = pos_store.pop_matching_position(condition_id, token_id)
            _emit_redemption_event(on_event, payload, tracked_pos, tx_hash)
            _redeemed_conditions.add(condition_id)
            nonce += 1
        except Exception as exc:
            err = str(exc)
            if "nonce too low" in err or "already known" in err:
                log.info("Position already redeemed externally: %s", question[:40])
                tracked_pos = pos_store.pop_matching_position(condition_id, token_id)
                _emit_redemption_event(on_event, payload, tracked_pos, "")
                _redeemed_conditions.add(condition_id)
                nonce += 1
            else:
                log.error("Redeem failed for %s: %s", question[:40], exc)

    # Under the relayer/Safe path, redeemed USDC already lands in the Safe
    # (funder) — the EOA→funder sweep doesn't apply and would need gas.
    if POLYMARKET_FUNDER and not use_relayer:
        try:
            _claim_to_funder()
        except Exception as exc:
            log.error("Claim failed: %s", exc)
