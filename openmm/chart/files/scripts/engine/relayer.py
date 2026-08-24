"""Polymarket Relayer v2 client — gasless on-chain submission for Gnosis Safe.

We sign the SafeTx (EIP-712) exactly as redemptions._send_tx_via_safe does, then
hand it to the relayer instead of broadcasting via eth_sendRawTransaction. The
relayer wraps our (to, data) in the Safe execTransaction and pays the gas.

  POST /submit            -> {"transactionID": ..., "state": "STATE_NEW"}
  GET  /transaction?id=.. -> {..., "state": ..., "transactionHash": "0x.."}

Docs: https://docs.polymarket.com/api-reference/relayer/submit-a-transaction
Only the Safe write is relayed; the Safe nonce is a read-only eth_call (no gas).
"""
from __future__ import annotations

import time

import requests

from config import (
    CHAIN_ID, POLYGON_RPC, POLYMARKET_FUNDER, POLYMARKET_PK,
    RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS, RELAYER_URL, log,
)

ZERO_ADDR = "0x0000000000000000000000000000000000000000"
_TERMINAL_FAIL = ("FAIL", "REVERT", "ERROR", "CANCEL", "DROPPED")


def _rpc(method: str, params: list):
    resp = requests.post(POLYGON_RPC, json={"jsonrpc": "2.0", "id": 1,
                                            "method": method, "params": params}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def _safe_nonce(safe: str) -> int:
    from eth_utils import keccak
    sel = keccak(b"nonce()")[:4]
    return int(_rpc("eth_call", [{"to": safe, "data": "0x" + sel.hex()}, "latest"]), 16)


def _sign_safe_tx(to_addr: str, data_bytes: bytes, safe: str, safe_nonce: int) -> str:
    """EIP-712 SafeTx signature (owner = POLYMARKET_PK). Mirrors the proven
    signing in redemptions._send_tx_via_safe; value/gas/tokens all zero."""
    from eth_abi import encode
    from eth_utils import keccak
    from eth_keys import keys as eth_keys_lib

    DOMAIN_TYPEHASH = keccak(b"EIP712Domain(uint256 chainId,address verifyingContract)")
    SAFE_TX_TYPEHASH = keccak(
        b"SafeTx(address to,uint256 value,bytes data,uint8 operation,"
        b"uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,"
        b"address refundReceiver,uint256 nonce)"
    )
    domain_sep = keccak(encode(
        ["bytes32", "uint256", "address"], [DOMAIN_TYPEHASH, CHAIN_ID, safe]))
    safe_tx_hash = keccak(encode(
        ["bytes32", "address", "uint256", "bytes32", "uint8",
         "uint256", "uint256", "uint256", "address", "address", "uint256"],
        [SAFE_TX_TYPEHASH, to_addr, 0, keccak(data_bytes), 0,
         0, 0, 0, ZERO_ADDR, ZERO_ADDR, safe_nonce]))
    msg_hash = keccak(b"\x19\x01" + domain_sep + safe_tx_hash)

    pk = eth_keys_lib.PrivateKey(bytes.fromhex(POLYMARKET_PK.removeprefix("0x")))
    sig = pk.sign_msg_hash(msg_hash)
    return "0x" + (sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big")
                   + bytes([sig.v + 27])).hex()


def _headers() -> dict:
    return {
        "RELAYER_API_KEY": RELAYER_API_KEY,
        "RELAYER_API_KEY_ADDRESS": RELAYER_API_KEY_ADDRESS,
        "Content-Type": "application/json",
    }


def submit_transaction(to: str, data_hex: str) -> str:
    """Sign + submit a Safe tx through the relayer. Returns the transactionID."""
    from eth_utils import to_checksum_address
    from eth_account import Account

    if not (RELAYER_API_KEY and RELAYER_API_KEY_ADDRESS):
        raise RuntimeError("relayer not configured (RELAYER_API_KEY / _ADDRESS)")
    if not POLYMARKET_FUNDER:
        raise RuntimeError("relayer requires POLYMARKET_FUNDER (the Safe address)")

    signer = Account.from_key(POLYMARKET_PK).address
    safe = to_checksum_address(POLYMARKET_FUNDER)
    to_addr = to_checksum_address(to)
    data_bytes = bytes.fromhex(data_hex.removeprefix("0x"))
    safe_nonce = _safe_nonce(safe)
    signature = _sign_safe_tx(to_addr, data_bytes, safe, safe_nonce)

    body = {
        "from": signer,
        "to": to_addr,
        "proxyWallet": safe,
        "data": data_hex if data_hex.startswith("0x") else "0x" + data_hex,
        "nonce": str(safe_nonce),
        "signature": signature,
        "signatureParams": {
            "gasPrice": "0", "operation": "0", "safeTxnGas": "0",
            "baseGas": "0", "gasToken": ZERO_ADDR, "refundReceiver": ZERO_ADDR,
        },
        "type": "SAFE",
    }
    log.info("RELAYER submit REQUEST  to=%s safe_nonce=%d", to_addr, safe_nonce)
    resp = requests.post(f"{RELAYER_URL}/submit", json=body, headers=_headers(), timeout=15)
    log.info("RELAYER submit RESPONSE  status=%d body=%s", resp.status_code, resp.text[:500])
    resp.raise_for_status()
    j = resp.json()
    tx_id = j.get("transactionID") or j.get("transactionId")
    if not tx_id:
        raise RuntimeError(f"relayer: no transactionID in response: {j}")
    return tx_id


def get_status(transaction_id: str) -> dict:
    resp = requests.get(f"{RELAYER_URL}/transaction", params={"id": transaction_id},
                        headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def poll_until_hash(transaction_id: str, timeout: float = 120.0, interval: float = 2.0) -> str:
    """Poll until the tx is broadcast (transactionHash present) or it fails/times out."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        try:
            last = get_status(transaction_id)
        except Exception as exc:
            log.warning("RELAYER status poll error: %s", exc)
            time.sleep(interval); continue
        state = str(last.get("state", "")).upper()
        tx_hash = last.get("transactionHash") or last.get("hash")
        if tx_hash:
            log.info("RELAYER tx broadcast  id=%s state=%s hash=%s", transaction_id, state, tx_hash)
            return tx_hash
        if any(f in state for f in _TERMINAL_FAIL):
            raise RuntimeError(f"relayer tx {transaction_id} failed: state={state} body={last}")
        time.sleep(interval)
    raise TimeoutError(f"relayer tx {transaction_id} no hash after {timeout}s (last={last})")


def submit_and_wait(to: str, data_hex: str, timeout: float = 120.0) -> str:
    """Submit a Safe tx via the relayer and return the on-chain hash once broadcast."""
    return poll_until_hash(submit_transaction(to, data_hex), timeout=timeout)
